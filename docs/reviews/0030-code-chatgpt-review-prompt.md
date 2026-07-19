# V1.0.9 Registry Introspection — ChatGPT Code Review Prompt

## Context

V1.0.9 ADR-0030 Registry Introspection — **implementation review** after ADR Approved 9.62/10.

**Cycle:**
- V1.0.6 ADR-0026 StageDescriptor → ADR 9.95/10 + Code 9.95/10 → Accepted
- V1.0.7 ADR-0027 RuntimeMetadata → ADR 9.85/10 + Code 9.88/10 → Accepted (682944a)
- V1.0.8 ADR-0028 Metadata Access API → ADR 9.91/10 + Code 9.94/10 → Accepted (35a4a20)
- V1.0.8 ADR-0029 Stage Registry → ADR 9.93/10 + Code 9.72/10 → Accepted Rev1 (1d38530)
- **V1.0.9 ADR-0030 Registry Introspection → ADR 9.62/10 Accepted (6777f35)**
- **V1.0.9 Implementation → review pending (commit 7decec8)**

This is the **code-layer review** (post-ADR-accepted). ADR-0030 已审 9.62/10 APPROVED，5 项 minor revisions (R1-R5) 已采纳。本审核评估：
1. 实施是否符合 ADR-0030 设计
2. R1-R5 修订是否正确落地
3. 代码质量 (一致性 / 简洁性 / 不变量)
4. 测试覆盖 (40 tests / 10 classes)
5. 向后兼容 (V1.0.8 132 tests → V1.0.9 398 tests 全通过)

## Files Changed (2 files, 849 insertions / 18 deletions)

### Modified Files

1. **`planner/stage_registry.py`** (626 lines, +416 / -18)
   - V1.0.9 Introspection extension on top of V1.0.8 StageRegistry
   - **New imports:** `json`, `dataclass.field`, `datetime`
   - **New constant:** `VALID_SOURCES = frozenset({"builtin", "third_party", "test"})` (R2)
   - **New dataclasses:** `StageInfo` (frozen), `StageSummary` (frozen)
   - **Extended method:** `register()` adds `source` + `requires` kwargs (V1.0.8 backward compat)
   - **New private field:** `StageRegistry._info: Dict[str, StageInfo]`
   - **Sync cleanup:** `unregister()` / `clear()` also clear `_info`
   - **8 new Introspection APIs:** `info` / `describe_all` / `summary` / `list_builtin` / `list_third_party` / `find_stages_needing` / `to_dict` / `to_json`
   - **New helper:** `_descriptor_to_dict(d)` (V1.0.10 ADR-0031 将重构为 delegate)
   - **Updated factory:** `_register_builtin_stages` 用 `source="builtin"` + `requires=("router",)` / `("store",)` / `()`

2. **`tests/test_stage_registry_introspection.py`** (433 lines, 40 new tests, NEW)
   - TestStageInfoDataclass (3) — frozen / defaults
   - TestRegisterV19Extension (5) — source / requires / V1.0.8 backward compat
   - TestInfoDescribeAll (4) — info / describe_all
   - TestSummary (3) — summary returns StageSummary
   - TestListBySource (4) — list_builtin / list_third_party
   - TestFindStagesNeeding (6, R5 AND) — find_stages_needing with issubset
   - TestSerialization (6, R4 stability) — to_dict / to_json / schema stable
   - TestInfoCleanup (3) — unregister / clear / replace sync cleanup
   - TestDefaultRegistryV19 (4) — builtin source + requires declaration
   - TestValidSourcesWarning (2, R2) — VALID_SOURCES + warning (no raise)

## Code Excerpts (Key V1.0.9 Additions)

### Excerpt 1: StageInfo / StageSummary dataclasses (R3 adopted)

```python
VALID_SOURCES: FrozenSet[str] = frozenset({"builtin", "third_party", "test"})


@dataclass(frozen=True)
class StageInfo:
    """Stage 完整信息 (V1.0.9 Introspection, ADR-0030)."""
    descriptor: StageDescriptor
    source: str = "third_party"            # "builtin" | "third_party" | "test"
    requires: Tuple[str, ...] = ()          # runtime dep names
    # R3 (ChatGPT 9.62/10): register() 永远生成 now, 用 default_factory
    registered_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class StageSummary:
    """Stage 简短摘要 (V1.0.9 Introspection)."""
    name: str
    role: str
    capabilities: FrozenSet[str]
    source: str
    requires: Tuple[str, ...]
```

**R3 注:** ADR 草案中 `registered_at: Optional[datetime]`，ChatGPT 审核建议改为非 Optional (register() 永远生成 now)。实施已采纳，用 `field(default_factory=datetime.now)` 保证 frozen dataclass 可设默认值。

### Excerpt 2: register() V1.0.9 扩展 (R2 adopted)

```python
def register(
    self,
    stage: Stage,
    *,
    replace: bool = False,
    source: str = "third_party",   # V1.0.9 NEW
    requires: Tuple[str, ...] = (), # V1.0.9 NEW
) -> None:
    descriptor = get_descriptor(stage)
    name = descriptor.name

    # V1.0.9 R2: source 校验 (warning only, V1.x 开放字符串)
    if source not in VALID_SOURCES:
        logger.warning(
            "Stage %r registered with unknown source=%r. "
            "Valid sources: %s. V1.x allows open string, V1.1 will enforce enum.",
            name, source, sorted(VALID_SOURCES),
        )

    if name in self._stages and not replace:
        raise KeyError(
            f"Stage {name!r} already registered. "
            f"Use replace=True to overwrite."
        )
    if name in self._stages:
        self._unindex(name)
    self._stages[name] = stage
    self._index(descriptor)
    # V1.0.9: 记录 StageInfo
    self._info[name] = StageInfo(
        descriptor=descriptor,
        source=source,
        requires=requires,
    )
```

**R2 注:** ADR 草案未明确 source 校验策略。ChatGPT 审核建议 V1.x 开放字符串 + warning (不 raise)，V1.1 改为严格 Enum。实施已采纳。

### Excerpt 3: unregister() / clear() 同步清理 _info

```python
def unregister(self, name: str) -> Optional[Stage]:
    stage = self._stages.pop(name, None)
    if stage is not None:
        self._unindex(name)
        # V1.0.9: 同步清理 _info
        self._info.pop(name, None)
    return stage

def clear(self) -> None:
    self._stages.clear()
    self._by_role.clear()
    self._by_capability.clear()
    self._info.clear()
```

**注:** V1.0.8 没有 `_info`，V1.0.9 新增的 `_info` 必须在 unregister/clear/replace 中同步清理，否则会泄露 StageInfo (memory leak + 不一致)。TestInfoCleanup 3 个测试覆盖此场景。

### Excerpt 4: 8 Introspection APIs

```python
def info(self, name: str) -> Optional[StageInfo]:
    """返回 Stage 完整信息 (V1.0.9 ADR-0030)."""
    return self._info.get(name)

def describe_all(self) -> Dict[str, StageDescriptor]:
    """返回所有 Stage 的 descriptor (V1.0.9 ADR-0030)."""
    return {name: get_descriptor(s) for name, s in self._stages.items()}

def summary(self) -> List[StageSummary]:
    """返回所有 Stage 的简短摘要 (V1.0.9 ADR-0030)."""
    result: List[StageSummary] = []
    for name, info in self._info.items():
        d = info.descriptor
        result.append(StageSummary(
            name=d.name,
            role=d.role,
            capabilities=d.capabilities,
            source=info.source,
            requires=info.requires,
        ))
    return result

def list_builtin(self) -> List[str]:
    """列出所有 source="builtin" 的 Stage name (V1.0.9 ADR-0030)."""
    return [n for n, info in self._info.items() if info.source == "builtin"]

def list_third_party(self) -> List[str]:
    """列出所有 source="third_party" 的 Stage name (V1.0.9 ADR-0030)."""
    return [n for n, info in self._info.items() if info.source == "third_party"]

def find_stages_needing(self, *deps: str) -> List[str]:
    """列出所有 requires 包含指定 deps 的 Stage name (V1.0.9 ADR-0030, R5 AND 语义).

    语义 (R5 采纳 ChatGPT 9.62/10):
      - AND query (issubset): 返回 requires **包含所有** deps 的 Stage
      - 例: find_stages_needing("router", "store") → 同时需要 router 和 store 的 Stage
      - 未来 V1.1 评估: 增加 mode="any" 参数支持 OR query
    """
    if not deps:
        return []
    dep_set = set(deps)
    return [
        n for n, info in self._info.items()
        if dep_set.issubset(set(info.requires))
    ]

def to_dict(self) -> Dict[str, Any]:
    """序列化 Registry 状态为 dict (V1.0.9 ADR-0030)."""
    return {
        "stages": [
            {
                "name": info.descriptor.name,
                "descriptor": _descriptor_to_dict(info.descriptor),
                "source": info.source,
                "requires": list(info.requires),
                "registered_at": info.registered_at.isoformat() if info.registered_at else None,
            }
            for info in self._info.values()
        ],
        "roles": sorted(self.roles()),
        "capabilities": sorted(self.capabilities()),
        "default_order": list(self.default_order()),
    }

def to_json(self, *, indent: Optional[int] = 2) -> str:
    """序列化 Registry 状态为 JSON 字符串 (V1.0.9 ADR-0030)."""
    return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
```

### Excerpt 5: _descriptor_to_dict helper (V1.0.10 ADR-0031 将重构)

```python
def _descriptor_to_dict(d: StageDescriptor) -> Dict[str, Any]:
    """StageDescriptor → dict (V1.0.9 helper, ADR-0030).

    V1.0.10 ADR-0031 (Metadata Serialization) 后:
      - 此 helper 将重构为 StageDescriptor.to_dict() delegate
      - 当前保持为模块级 helper (避免提前耦合)
    """
    return {
        "name": d.name,
        "role": d.role,
        "version": d.version,
        "capabilities": sorted(d.capabilities),
        "idempotent": d.idempotent,
        "has_side_effects": d.has_side_effects,
        "always_run_after_stop": d.always_run_after_stop,
        "experimental": d.experimental,
        "description": d.description,
        "owner": d.owner,
    }
```

### Excerpt 6: _register_builtin_stages V1.0.9 扩展

```python
def _register_builtin_stages(registry: StageRegistry) -> None:
    """注册 5 个 built-in Stage (V1.0.9 扩展 source + requires)."""
    from planner.pipeline import RouteStage, MetricsStage
    from planner.stages.retry_stage import RetryStage
    from planner.stages.checkpoint_stage import CheckpointStage
    from planner.stages.condition_stage import ConditionStage

    registry.register(
        RouteStage(router=None),                  # V1.0.8 Rev1 R4 stub
        source="builtin",
        requires=("router",),                     # V1.0.9 NEW
    )
    registry.register(
        RetryStage(),
        source="builtin",
        requires=(),
    )
    registry.register(
        CheckpointStage(store=_NullStore()),      # V1.0.8 Rev1 R4 stub
        source="builtin",
        requires=("store",),                      # V1.0.9 NEW
    )
    registry.register(
        ConditionStage(condition=lambda c: True, on_true="continue"),
        source="builtin",
        requires=(),
    )
    registry.register(
        MetricsStage(),
        source="builtin",
        requires=(),
    )
```

### Excerpt 7: TestSerialization R4 stability test

```python
def test_to_json_schema_stable(self, clean_default):
    """R4 (ChatGPT 9.62/10): to_json() schema keys 跨版本稳定."""
    data = json.loads(default_registry().to_json())
    assert set(data.keys()) == {"stages", "roles", "capabilities", "default_order"}
    for stage in data["stages"]:
        assert set(stage.keys()) == {
            "name", "descriptor", "source", "requires", "registered_at"
        }
        assert set(stage["descriptor"].keys()) == {
            "name", "role", "version", "capabilities", "idempotent",
            "has_side_effects", "always_run_after_stop", "experimental",
            "description", "owner",
        }
```

**R4 注:** ADR 草案测试策略未明确 schema stability test。ChatGPT 审核建议增加 `test_to_json_schema_stable` 以保证未来 ADR-0031 (Metadata Serialization) 不会破坏 schema。实施已采纳。

### Excerpt 8: TestFindStagesNeeding R5 AND 语义 test

```python
def test_find_stages_needing_multiple_and(self, clean_default):
    """find_stages_needing("router", "store") 返回 [] (AND 语义, 无 Stage 同时需要两者)."""
    reg = default_registry()
    result = reg.find_stages_needing("router", "store")
    assert result == []

def test_find_stages_needing_router(self, clean_default):
    """find_stages_needing("router") 返回 ["route"] (route Stage requires router)."""
    reg = default_registry()
    result = reg.find_stages_needing("router")
    assert result == ["route"]
```

**R5 注:** ADR 草案 `find_stages_needing` 语义未明确 AND/OR。ChatGPT 审核建议明确 AND (issubset)，未来 V1.1 评估 mode="any"。实施已采纳。

## Key Implementation Decisions

### Decision 1: `_info` 作为平行 dict 而非嵌入 Stage

**实施:** StageRegistry 持有 `self._info: Dict[str, StageInfo]`，与 `self._stages` / `self._by_role` / `self._by_capability` 平行。

**Why:** Stage 实例不被 Registry 修改 (V1.0.8 不变量 "Registry 仅持引用")。StageInfo 是 Registry 上下文信息 (source / requires / registered_at)，不应污染 Stage 实例。

**Alternative considered:** 在 StageDescriptor 加 `source` / `requires` 字段。**Rejected** — StageDescriptor 是 Stage 自身静态 metadata (V1.0.6 已稳定)，source/requires 是 Registry 上下文 (ADR-0030 §5 rejected alternative #2)。

### Decision 2: `find_stages_needing` 用 `issubset` 而非 `set.intersection`

```python
dep_set = set(deps)
return [
    n for n, info in self._info.items()
    if dep_set.issubset(set(info.requires))
]
```

**Why:** `issubset` 语义是 "deps 是 requires 的子集" = "Stage requires **包含所有** deps" = AND query。如果用 `intersection` 则是 OR query (任一 dep 出现即匹配)。

**R5 明确:** ADR 草案未明确，ChatGPT 审核建议 AND。未来 V1.1 评估增加 `mode="any"` 参数。

### Decision 3: `registered_at` 用 `default_factory` 而非 `datetime.now()` 字面量

```python
@dataclass(frozen=True)
class StageInfo:
    ...
    registered_at: datetime = field(default_factory=datetime.now)
```

**Why:** frozen dataclass 不能用 `datetime.now()` 作为字段默认值 (会评估一次, 所有实例共享同一 timestamp)。`default_factory` 每次 instantiate 时调用 `datetime.now()`，每个 StageInfo 有独立的 registered_at。

**ADR 一致性:** ADR §2.1 写的是 `registered_at: datetime = field(default_factory=datetime.now)`，代码与 ADR 一致。

### Decision 4: `to_dict()` 中 `registered_at` 仍用 `if info.registered_at else None`

```python
"registered_at": info.registered_at.isoformat() if info.registered_at else None,
```

**Why 防御式编程:** 虽然 R3 已将 `registered_at` 改为非 Optional (永远有值)，但 `to_dict()` 序列化时仍保留 None 检查。原因:
- 未来若 V1.x 重新引入 Optional (e.g. 允许 register 时显式传 None 跳过 timestamp)
- JSON schema stability (R4 test 要求 key 存在, 但 value 可为 None)
- 防御外部 mock (测试 fixture 可能传 None)

**Alternative considered:** 移除 None 检查，直接 `info.registered_at.isoformat()`。**Rejected** — 失去防御性，且 JSON output 不变 (registered_at 永远是 ISO string)。

### Decision 5: `_descriptor_to_dict` 是模块级 helper (非 StageDescriptor 方法)

```python
# planner/stage_registry.py (模块级)
def _descriptor_to_dict(d: StageDescriptor) -> Dict[str, Any]:
    return {
        "name": d.name, "role": d.role, ...
    }
```

**Why:**
1. V1.0.6 StageDescriptor 已 Accepted 9.95/10，不应在 V1.0.9 加 `to_dict()` 方法 (避免 Core Freeze 风险)
2. ADR-0031 (V1.0.10 Metadata Serialization) 会系统化处理 metadata → dict 的序列化
3. 当前 helper 是 _前缀 (private)，未来 ADR-0031 可重构为 StageDescriptor delegate

**ADR 一致性:** ADR §2.1 明确 `_descriptor_to_dict` 为 V1.0.9 helper，V1.0.10 ADR-0031 后重构。

### Decision 6: VALID_SOURCES 是 frozenset 而非 Enum

```python
VALID_SOURCES: FrozenSet[str] = frozenset({"builtin", "third_party", "test"})
```

**Why:**
1. ADR-0030 R2 明确 "V1.x 开放字符串 + warning，V1.1 严格 Enum"
2. 当前 source 仍是 str 类型 (不是 Enum)
3. VALID_SOURCES 仅用于 warning check (`if source not in VALID_SOURCES`)
4. V1.1 改 Enum 时，VALID_SOURCES 改为 `FrozenSet[SourceEnum]`，warning 改 raise

### Decision 7: 测试 fixture 用 reset_default_registry (V1.0.8 T1 helper)

```python
@pytest.fixture
def clean_default():
    reset_default_registry()
    yield
    reset_default_registry()
```

**Why:** V1.0.8 T1 (ChatGPT 9.93/10) 提供 `reset_default_registry()` 用于测试隔离。V1.0.9 测试沿用此 fixture，确保 `default_registry()` 在每个测试前都是干净状态 (5 个 builtin Stage)。

## ADR vs Code Discrepancies (for ChatGPT evaluation)

1. **ADR §2.1 `to_dict()` 中 `registered_at` 处理:**
   - ADR 写: `"registered_at": info.registered_at.isoformat()` (直接调用, 无 None 检查)
   - 代码写: `info.registered_at.isoformat() if info.registered_at else None` (有 None 检查)
   - 原因: 防御式编程 (见 Decision 4)
   - **问题:** 此偏离是否可接受？还是应严格遵循 ADR (移除 None 检查)？

2. **ADR §2.2 `_register_builtin_stages` 用 `_NullStore`:**
   - ADR-0030 草案未提及 `_NullStore` (V1.0.8 Rev1 R4 引入)
   - 代码引用 V1.0.8 Rev1 的 `_NullStore` 实例作为 CheckpointStage stub store
   - 原因: ADR-0030 假设 V1.0.8 Rev1 已落地 (依赖关系)
   - **问题:** 此跨 ADR 依赖是否需要在 ADR-0030 §2.2 显式声明？

3. **ADR §6 测试策略 `test_register_unknown_source_allowed`:**
   - ADR 写: `test_register_unknown_source_allowed` (测试 source="internal_plugin")
   - 代码实现: `test_register_unknown_source_warns_not_raises` (测试 source="internal_plugin")
   - 差异: 测试名略不同，但语义一致
   - **问题:** 此命名差异是否需要修正？

## Test Coverage Summary (40 tests, 10 classes)

| Class | Tests | Coverage | ADR Section |
|-------|-------|----------|-------------|
| TestStageInfoDataclass | 3 | StageInfo/StageSummary frozen + defaults | §2.1 |
| TestRegisterV19Extension | 5 | source / requires / V1.0.8 backward compat | §2.1, §3 |
| TestInfoDescribeAll | 4 | info() / describe_all() | §2.1 |
| TestSummary | 3 | summary() returns StageSummary | §2.1 |
| TestListBySource | 4 | list_builtin() / list_third_party() | §2.1 |
| TestFindStagesNeeding | 6 | find_stages_needing() AND 语义 (R5) | §2.1, R5 |
| TestSerialization | 6 | to_dict() / to_json() / schema stable (R4) | §2.1, R4 |
| TestInfoCleanup | 3 | unregister / clear / replace sync _info | §2.1 |
| TestDefaultRegistryV19 | 4 | default_registry builtin source + requires | §2.2 |
| TestValidSourcesWarning | 2 | VALID_SOURCES + warning (R2) | R2 |

**Regression:** 398/398 V1.0.x core tests pass (V1.0.6-V1.0.8 全部 + V1.0.9 新增)

## Questions for ChatGPT (8 questions)

**Q1: StageInfo 设计**
StageInfo 用 frozen dataclass + `_info: Dict[str, StageInfo]` 平行 dict 而非嵌入 Stage / StageDescriptor。此设计是否正确？还是有更好的 alternatives (e.g. Stage 持有 StageInfo 引用 / Registry 返回 tuple)?

**Q2: registered_at 用 default_factory**
`registered_at: datetime = field(default_factory=datetime.now)` 在 frozen dataclass 中正确吗？有什么 subtle bug (e.g. 时区 / mock 困难 / 测试不可重复)?

**Q3: source warning 而非 raise**
V1.x 用 `logger.warning` 而非 `raise ValueError` 处理 unknown source。是否过宽？是否应该至少 `warnings.warn(DeprecationWarning)` 让用户可 filter?

**Q4: find_stages_needing AND 语义**
`dep_set.issubset(set(info.requires))` 实现是否正确？有无 edge case (e.g. deps 重复 / requires 空 / deps 空)? 当前 `if not deps: return []` 是否合理?

**Q5: to_dict() schema stability**
R4 test 锁定 schema keys。但如果未来 V1.1 加新字段 (e.g. `last_used_at`)，schema 变化如何处理？是否需要 `schema_version` 字段?

**Q6: _descriptor_to_dict helper 位置**
`_descriptor_to_dict` 当前是 `planner/stage_registry.py` 模块级 helper。V1.0.10 ADR-0031 (Metadata Serialization) 应该:
- (a) 重构为 `StageDescriptor.to_dict()` 方法 (改动 V1.0.6 Core)
- (b) 移到 `planner/metadata_serialization.py` 模块
- (c) 保持当前模块级 helper
哪个最优？

**Q7: VALID_SOURCES frozenset**
`VALID_SOURCES = frozenset({"builtin", "third_party", "test"})` 是否应该含 `"deprecated"` 或 `"experimental"`? ADR §5 rejected alternative 提到这些不应加入 source (因为 experimental 已在 StageDescriptor)。是否同意?

**Q8: 测试覆盖盲点**
40 tests 覆盖 10 个测试类。是否有重要场景未覆盖? 例如:
- (a) 多个第三方 Stage 同 source 注册
- (b) `replace=True` 时 source/requires 是否正确覆盖 (TestInfoCleanup.test_replace_updates_info 已覆盖, 是否够?)
- (c) `to_json()` indent=None (紧凑模式) 是否需要 test?
- (d) `find_stages_needing()` 传 0 个参数 (已覆盖) / 1 个 / 多个 (已覆盖) — 是否需要 OR 模式 test?

## Review Focus (for ChatGPT)

请评估以下 8 个维度 (1-10 评分 + 简短评价):

1. **架构方向** — V1.0.9 Introspection 扩展是否符合 V1.0.x 演进路径?
2. **API 一致性** — 8 个 Introspection API 是否与 V1.0.8 StageRegistry 风格一致?
3. **向后兼容** — V1.0.8 132 tests 全通过 + V1.0.8 register() 调用兼容性
4. **数据结构** — StageInfo / StageSummary frozen dataclass 设计
5. **替代方案质量** — Decision 1-7 (尤其是 Decision 1 `_info` 平行 dict, Decision 5 helper 位置)
6. **测试策略** — 40 tests / 10 classes 覆盖 + R4 stability test + R5 AND test
7. **实施计划** — R1-R5 修订落地正确性
8. **V1.0.10 演化规划** — ADR-0031 Metadata Serialization 应该先做哪部分?

## 总分要求

- **通过门槛**: 9.0/10
- **目标**: 9.5+/10
- **未通过**: < 9.0 → 必改项 (blocking)
- **通过**: 9.0-9.5 → minor revisions (non-blocking)
- **优秀**: 9.5+ → APPROVED

请给出:
1. 总分 (1-10)
2. 8 个维度评分 + 简短评价
3. 8 个问题 (Q1-Q8) 逐项结论
4. 关键修订要求 (合并前必改 + 建议改)
5. 下一步路线建议 (V1.0.10 ADR-0031 优先级)
