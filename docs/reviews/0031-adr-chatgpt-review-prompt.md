# V1.0.10 ADR-0031 Metadata Serialization — ChatGPT ADR Review Prompt

## Context

V1.0.10 ADR-0031 Metadata Serialization — **ADR review** (pre-implementation).

**Cycle:**
- V1.0.6 ADR-0026 StageDescriptor → ADR 9.95/10 + Code 9.95/10 → Accepted
- V1.0.7 ADR-0027 RuntimeMetadata → ADR 9.85/10 + Code 9.88/10 → Accepted (682944a)
- V1.0.8 ADR-0028 Metadata Access API → ADR 9.91/10 + Code 9.94/10 → Accepted (35a4a20)
- V1.0.8 ADR-0029 Stage Registry → ADR 9.93/10 + Code 9.72/10 → Accepted Rev1 (1d38530)
- V1.0.9 ADR-0030 Registry Introspection → ADR 9.62/10 + Code 9.62/10 → Accepted (688cfe9)
- **V1.0.10 ADR-0031 Metadata Serialization → ADR review pending**

ChatGPT V1.0.9 代码审核 §V1.0.10 路线建议 P0: 建立 `planner/metadata_serialization.py` 统一序列化层。

## ADR Document

完整 ADR 见 `docs/adr/0031-metadata-serialization.md`。

### §1 背景与目标

V1.0.6 - V1.0.9 引入 4 个独立 metadata 类型 (StageDescriptor / RuntimeMetadata / StageInfo / ConditionEval)，但序列化逻辑分散:
- `_descriptor_to_dict` 在 stage_registry.py (V1.0.9 helper, 位置违反 SRP)
- `ConditionEval.to_dict()` 在 condition_stage.py (V1.0.4)
- StageDescriptor / RuntimeMetadata / StageInfo 无 `to_dict()`

**V1.0.10 目标** (不破坏 V1.0.6 - V1.0.9 API):
1. 新建 `planner/metadata_serialization.py` 模块 (5 个公开 API)
2. 各 dataclass 加 `to_dict()` 方法 (delegate to serialize module)
3. 迁移 `_descriptor_to_dict` 到序列化模块 (V1.0.9 backward compat)
4. `StageRegistry.to_dict()` 重构 (用 serialize_stage_info)
5. **不引入 schema_version** (V1.1 deferred, ChatGPT M1)
6. **不引入 UTC timestamp** (V1.1 deferred, ChatGPT M2)

### §2 设计 (核心)

#### §2.1 新建模块 `planner/metadata_serialization.py`

```python
METADATA_SCHEMA_VERSION: Optional[int] = None  # V1.1 启用

def serialize_descriptor(d: StageDescriptor) -> Dict[str, Any]:
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

def serialize_stage_info(info: StageInfo) -> Dict[str, Any]:
    return {
        "name": info.descriptor.name,
        "descriptor": serialize_descriptor(info.descriptor),
        "source": info.source,
        "requires": list(info.requires),
        "registered_at": info.registered_at.isoformat() if info.registered_at else None,
    }

def serialize_runtime_metadata(rm: RuntimeMetadata) -> Dict[str, Any]:
    return {
        "server_metrics": dict(rm.server_metrics),
        "condition_eval": (
            serialize_condition_eval(rm.condition_eval)
            if rm.condition_eval is not None
            else None
        ),
        "stopped_by": rm.stopped_by,
        "plan": dict(rm.plan),
        "custom": dict(rm.custom),
    }

def serialize_condition_eval(ce: ConditionEval) -> Dict[str, Any]:
    return {
        "stage": ce.stage,
        "condition_name": ce.condition_name,
        "result": ce.result,
        "action": ce.action,
        "timestamp": ce.timestamp,
        "stopped_by": ce.stopped_by,
    }

def to_json(d: Dict[str, Any], *, indent: Optional[int] = 2) -> str:
    return json.dumps(d, indent=indent, ensure_ascii=False)
```

#### §2.2 - §2.5 各 dataclass 加 `to_dict()` (delegate)

```python
# StageDescriptor (V1.0.6 → V1.0.10 加方法)
@dataclass(frozen=True)
class StageDescriptor:
    # ... V1.0.6 字段不变
    def to_dict(self) -> Dict[str, Any]:
        from planner.metadata_serialization import serialize_descriptor
        return serialize_descriptor(self)

# StageInfo (V1.0.9 → V1.0.10)
@dataclass(frozen=True)
class StageInfo:
    # ... V1.0.9 字段不变
    def to_dict(self) -> Dict[str, Any]:
        from planner.metadata_serialization import serialize_stage_info
        return serialize_stage_info(self)

# RuntimeMetadata (V1.0.7 → V1.0.10)
@dataclass
class RuntimeMetadata:
    # ... V1.0.7 字段不变
    def to_dict(self) -> Dict[str, Any]:
        from planner.metadata_serialization import serialize_runtime_metadata
        return serialize_runtime_metadata(self)

# ConditionEval (V1.0.4 → V1.0.10 delegate, 保留 method)
@dataclass
class ConditionEval:
    # ... V1.0.4 字段不变
    def to_dict(self) -> dict:
        from planner.metadata_serialization import serialize_condition_eval
        return serialize_condition_eval(self)
```

#### §2.6 `_descriptor_to_dict` deprecated alias

```python
# planner/stage_registry.py
def _descriptor_to_dict(d: StageDescriptor) -> Dict[str, Any]:
    """V1.0.9 helper, V1.0.10 deprecated alias."""
    from planner.metadata_serialization import serialize_descriptor
    return serialize_descriptor(d)
```

#### §2.7 `StageRegistry.to_dict()` 重构 (schema 不变)

```python
def to_dict(self) -> Dict[str, Any]:
    from planner.metadata_serialization import serialize_stage_info
    return {
        "stages": [serialize_stage_info(info) for info in self._info.values()],
        "roles": sorted(self.roles()),
        "capabilities": sorted(self.capabilities()),
        "default_order": list(self.default_order()),
    }
```

### §3 关键设计决策

| # | Decision | Status |
|---|----------|--------|
| 3.1 | 序列化模块独立 vs 嵌入各 dataclass | ✅ 独立模块 + dataclass.to_dict() delegate |
| 3.2 | to_dict() 方法 vs helper function | ✅ 双 API (convenience + functional) |
| 3.3 | 不引入 schema_version | ✅ V1.1 deferred (ChatGPT M1) |
| 3.4 | 不引入 UTC timestamp | ✅ V1.1 deferred (ChatGPT M2) |
| 3.5 | lazy import 避免循环依赖 | ✅ 方法内 lazy import |
| 3.6 | ConditionEval.to_dict() 保留 backward compat | ✅ V1.0.4 API 不破坏 |

### §5 Rejected Alternatives

- 5.1 ❌ 各 dataclass 自带 to_dict() 无独立模块 (序列化分散)
- 5.2 ❌ 用 `dataclasses.asdict()` 替代自定义 to_dict() (不控制 schema)
- 5.3 ❌ JSON encoder class (过度抽象)
- 5.4 ❌ V1.0.10 引入 schema_version (R4 stability test 守护)
- 5.5 ❌ V1.0.10 引入 UTC timestamp (V1.1 distributed registry)
- 5.6 ❌ 序列化逻辑放 `planner/__init__.py` (import side-effect)
- 5.7 ❌ 用 pydantic / marshmallow (V1.0.x 零外部依赖)

### §6 测试策略 (~30 tests / 8 classes)

1. TestSerializeDescriptor (6 tests) — 含 R4 schema stability
2. TestSerializeStageInfo (5 tests) — 含 R4 schema stability
3. TestSerializeRuntimeMetadata (5 tests) — 含 R4 schema stability
4. TestSerializeConditionEval (3 tests) — 含 V1.0.4 backward compat
5. TestToDictMethods (6 tests) — V1.0.10 新增方法 + delegate 一致性
6. TestToJsonHelper (3 tests) — indent / compact / ensure_ascii
7. TestMigrationFromV109 (3 tests) — 迁移正确性 (V1.0.9 helper alias / StageRegistry 重构 / R4 守护)
8. TestSchemaStability (2 tests) — V1.0.10 不引入 schema_version

### §7 实施计划 (5 阶段)

1. 新建 `planner/metadata_serialization.py`
2. 各 dataclass 加 `to_dict()` 方法
3. 迁移 `_descriptor_to_dict` (deprecated alias)
4. 重构 `StageRegistry.to_dict()` (schema 不变)
5. 测试 + V1.0.6 - V1.0.9 回归 (398 + 30 ≈ 428 tests)

### §9 Open Questions (for ChatGPT, 8 questions)

**Q1**: 序列化模块位置 — `planner/metadata_serialization.py` vs `planner/metadata/serialization.py` vs `planner/serialize.py`?

**Q2**: to_dict() 方法 vs helper function 双 API 是否过设计? 还是只保留一种?

**Q3**: StageDescriptor.to_dict() 破坏 V1.0.6 Core Freeze? (方法不改变字段, 不破坏 frozen)

**Q4**: lazy import 是否合理? 还是应该:
- (a) 模块顶层 import (可能有循环)
- (b) TYPE_CHECKING + lazy import (当前方案)
- (c) 反转依赖 (metadata_serialization 用 Protocol)

**Q5**: ConditionEval.to_dict() 保留还是移除?
- (a) 保留 method (backward compat)
- (b) 移除 method, 仅用 serialize_condition_eval()
- (c) 保留 + DeprecationWarning

**Q6**: RuntimeMetadata.to_dict() 包含 ctx.metadata 兼容字段?
- (a) 仅包含 RuntimeMetadata 字段 (当前方案)
- (b) 合并 ctx.metadata 兼容字段 (需 ctx 引用)
- (c) 两个 API: to_dict() + to_full_dict(ctx)

**Q7**: serialize_xxx 函数签名是否要 schema_version 参数?
```python
def serialize_descriptor(d, *, schema_version: Optional[int] = None) -> dict:
```
还是 V1.0.10 不加, V1.1 评估?

**Q8**: 测试覆盖盲点? ~30 tests 是否够?

### §10 Review Focus (8 dimensions)

请评估以下 8 个维度 (1-10 评分 + 简短评价):

1. **架构方向** — 序列化模块独立 vs 嵌入各 dataclass
2. **API 一致性** — to_dict() 方法 + serialize_xxx() helper 双 API
3. **向后兼容** — V1.0.6/V1.0.7/V1.0.9 加 to_dict() 是否破坏 Core Freeze
4. **数据结构** — schema 稳定性 + R4 stability test 策略
5. **替代方案质量** — Rejected alternatives (5.1-5.7)
6. **测试策略** — ~30 tests / 8 classes + R4 stability 守护
7. **实施计划** — 5 阶段 (新建模块 → 加方法 → 迁移 helper → 重构 registry → 测试)
8. **V1.1 演化规划** — schema_version + UTC timestamp + source Enum 是否应在 V1.0.10 引入?

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
5. 下一步路线建议 (V1.0.11 ADR-0032 优先级)
