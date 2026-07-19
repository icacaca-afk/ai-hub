# V1.0.9 Registry Introspection — ChatGPT Code Review (Summary)

- **审核类型**: 代码层 (post-ADR Accepted)
- **Commit**: 7decec8 (V1.0.9 implement Registry Introspection)
- **审核时间**: 2026-07-19
- **总分**: **9.62 / 10** ✅ APPROVED
- **Blocking**: **NONE** → MERGE
- **R1-R5 落地**: 全部 ✅ 正确实施
- **Raw**: `0030-code-chatgpt-review-raw.txt`

## 八维评分

| # | 维度 | 分数 | 评价 |
|---|------|------|------|
| 1 | 架构方向 | 9.8/10 | Introspection 放在 Registry 层正确，没有污染 Stage/Descriptor |
| 2 | API 一致性 | 9.6/10 | API 风格延续 V1.0.8，命名清晰 |
| 3 | 向后兼容 | **10/10** | register() keyword extension，无破坏性变化 |
| 4 | 数据结构设计 | 9.7/10 | frozen dataclass + parallel metadata store 非常合理 |
| 5 | 替代方案质量 | 9.5/10 | Decision 1-7 大部分优秀 |
| 6 | 测试策略 | 9.7/10 | R4 schema stability + R5 AND test 很关键 |
| 7 | R1-R5 落地 | 9.8/10 | 修订全部正确实施 |
| 8 | V1.0.10 演化规划 | 9.2/10 | 方向正确，但 Serialization 需要更系统设计 |

## 总评

V1.0.9 Implementation 与 ADR-0030 设计高度一致，R1-R5 修订基本正确落地。该实现延续了 V1.0.6 → V1.0.8 的演进路线：

- StageDescriptor（静态身份）
- → RuntimeMetadata（运行状态）
- → Metadata Access API（访问入口）
- → Stage Registry（生命周期管理）
- → Registry Introspection（可观测性）

架构方向正确，没有破坏 V1.x Core Freeze 原则。没有 blocking issue。**建议合并**。

## 最大正确决定: `_info` 平行存储

整个实现最重要的架构选择。当前：

```
StageRegistry
├── _stages      name -> Stage instance
├── _by_role
├── _by_capability
└── _info        name -> StageInfo  ← V1.0.9 NEW
```

非常正确。StageDescriptor 描述"Stage 自己是什么"，StageInfo 描述"Registry 如何管理它"，两者不是同一生命周期。

如果把 source/requires 塞进 StageDescriptor，会导致：Descriptor 语义膨胀 + Core Freeze 被破坏 + Stage 自身 metadata 和 runtime context 混合。

**Decision 1: accepted (10/10)**

## Q1-Q8 逐项结论

### Q1: StageInfo 设计是否正确？ ✅

三个方案比较：
- Stage 持有 StageInfo ❌ Registry 污染 Stage
- Registry 返回 tuple ❌ API 不稳定
- Registry `_info` ✅ **最佳** (典型 Registry Metadata Pattern，类似 Kubernetes object metadata / Plugin registry metadata)

### Q2: registered_at default_factory 是否正确？ ✅

代码 `registered_at: datetime = field(default_factory=datetime.now)` 是 dataclass 推荐写法。避免 `datetime.now()` 作为字段默认值（只执行一次）。

**唯一 minor**: timezone。`datetime.now()` 产生 naive datetime。V1.1 建议 `datetime.now(timezone.utc)` 用于多机器同步 / distributed registry / audit log。**当前 V1.0 不需要修改**。

### Q3: unknown source warning 是否过宽？ ✅ (10/10)

`logger.warning` 比 `raise ValueError` 更适合 V1.x。Registry 是扩展系统，未来可能有 `source="company_internal_plugin"` / `source="community"`。现在 reject 会限制生态。

`warnings.warn` 不推荐 — logging 更适合 server / plugin loading / CLI；DeprecationWarning 是 API 生命周期工具，不适合 metadata validation。

### Q4: find_stages_needing AND 语义 ✅ (10/10)

`dep_set.issubset(set(info.requires))` 数学含义: `deps ⊆ requires` = "Stage requires ALL deps" = AND query。符合 `find_stages_needing("router", "store")` 语义。

Edge case 都正确处理：
- deps 重复 → set 后去重 ✅
- deps 空 → `if not deps: return []` ✅ (空查询返回全部会危险)
- requires 空 → 不匹配 ✅

### Q5: to_dict schema stability ✅ (9.3/10)

R4 是非常好的测试。**未来 V1.1 建议**: 增加 `"schema_version": 1` 字段，避免旧消费者不知道新字段（`last_used_at` / `health` / `metrics`）。**V1.0.10 不要现在改**。

### Q6: _descriptor_to_dict 最佳位置？ ✅ (9.5/10)

三个方案：
- **A. StageDescriptor.to_dict()** — 不推荐。StageDescriptor V1.0.6 已稳定，改动 core metadata 影响范围太大。
- **B. `planner/metadata_serialization.py`** — **长期最佳**。未来 `serialize_descriptor()` / `serialize_runtime_metadata()` / `serialize_stage_info()` 统一。
- **C. 当前模块级 helper** — **V1.0.9 正确**。不要提前抽象。

**结论**: V1.0.9 保持当前；V1.0.10 迁移到 `planner/metadata_serialization.py`。

### Q7: VALID_SOURCES 是否需要 deprecated/experimental？ ✅ (10/10)

**不同意加入**。保持 `{"builtin", "third_party", "test"}`。`source` 表示**来源**，不是**状态**。`experimental` 属于 StageDescriptor，`deprecated` 属于 RuntimeMetadata。

### Q8: 测试覆盖盲点 ✅ (9.7/10)

40 tests 覆盖很好：
- ✅ frozen / backward compat / cleanup / serialization / schema / AND query / default registry

补充建议（非 blocking）：
- (a) 多第三方 Stage — 不是必须（list_third_party 已验证）
- (b) replace=True — 已有 `test_replace_updates_info`，够
- (c) `indent=None` — 建议增加 minor test
- (d) OR mode — **不要测试**（当前设计没有 OR，属于 V1.1）

## ADR vs Code Discrepancies

### Issue 1: registered_at None check
- ADR: `info.registered_at.isoformat()` (直接调用)
- 代码: `info.registered_at.isoformat() if info.registered_at else None`
- **结论**: ✅ Accept (增强防御，未改变 schema，不是 ADR violation)

### Issue 2: _NullStore 是否需要 ADR 声明？
- ADR-0030 未提及 `_NullStore` (V1.0.8 Rev1 R4 引入)
- 代码引用 V1.0.8 Rev1 的 `_NullStore` 作为 CheckpointStage stub store
- **结论**: 建议补充 ADR dependency declaration (non-blocking)
- **采纳**: 已在 ADR-0030 §依赖补充 `_NullStore` (V1.0.8 Rev1 R4)

### Issue 3: test 名不同
- ADR: `test_register_unknown_source_allowed`
- 代码: `test_register_unknown_source_warns_not_raises`
- **结论**: 不用修改（代码名称更准确，ADR 可以更新）

## R1-R5 落地评价

| Revision | 状态 |
|----------|------|
| R1 (6 类 Capability 描述) | ✅ |
| R2 (source validation + warning) | ✅ excellent |
| R3 (default_factory) | ✅ |
| R4 (schema stability test) | ✅ very good |
| R5 (AND semantics) | ✅ important |

## Minor Suggestions (Non-blocking, deferred)

### M1 (V1.1): schema_version
```json
{
  "schema_version": 1,
  "stages": [...]
}
```
**Defer to V1.1** — 当前 schema 已被 R4 test 锁定，V1.1 加新字段时再引入 schema_version。

### M2 (V1.1): UTC timestamp
```python
datetime.now(timezone.utc)
```
**Defer to V1.1** — 当前 naive datetime 在单进程 Registry 足够。V1.1 distributed registry / audit log 时再改。

### M3 (V1.0.9 已采纳): ADR-0030 dependency declaration
在 ADR-0030 §依赖补充:
- V1.0.8 Rev1 `_NullStore` (R4 misuse guard)

方便未来维护理解 ADR dependency chain。

## V1.0.10 ADR-0031 路线建议

| 优先级 | 内容 |
|--------|------|
| **P0** | `planner/metadata_serialization.py` — `StageDescriptor → dict` / `StageInfo → dict` / `RuntimeMetadata → dict` 统一 |
| P1 | Schema versioning (`schema_version` 字段) |
| P2 | UTC timestamp (`datetime.now(timezone.utc)`) |
| P3 | 增强查询 (`find(role=, capability=, requires=, source=)` 统一 API) |

## Final Approval

```
V1.0.9 Registry Introspection

ADR:            9.62/10 Approved (6777f35)
Implementation: 9.62/10 Approved (7decec8)

Tests:          398/398 PASS (V1.0.x core)

Decision:       ✅ MERGE

Blocking:       NONE

Next:           Proceed V1.0.10 ADR-0031 Metadata Serialization
```
