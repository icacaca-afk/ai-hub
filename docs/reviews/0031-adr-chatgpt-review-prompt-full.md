# V1.0.10 ADR-0031 Metadata Serialization — Full ADR + Review Prompt

---

# PART 1: Full ADR Document

# ADR-0031: Metadata Serialization (V1.0.10)

- **里程碑**: V1.0.10
- **作者**: ai-hub core team
- **日期**: 2026-07-19
- **状态**: **Draft** (待 ChatGPT 审核)
- **依赖**:
  - [ADR-0026 StageDescriptor](0026-stage-descriptor.md) (V1.0.6 Accepted 9.95/10)
  - [ADR-0027 RuntimeMetadata](0027-runtime-metadata.md) (V1.0.7 Accepted 9.85/10)
  - [ADR-0028 Metadata Access API](0028-metadata-access-api.md) (V1.0.8 Accepted 9.94/10)
  - [ADR-0030 Registry Introspection](0030-registry-introspection.md) (V1.0.9 Accepted 9.62/10) — `_descriptor_to_dict` helper 迁移源
- **后续**: V1.0.11 ADR-0032 Pipeline Introspection (SHOULD) / ADR-0033 Predicate API (SHOULD) / ADR-0034 CLI Introspection (MAY)
- **ChatGPT 代码审核 (V1.0.9)**: 建议 P0 优先级建立 `planner/metadata_serialization.py` 统一序列化层 — `docs/reviews/0030-code-chatgpt-review.md` §V1.0.10 ADR-0031 路线建议

> **ADR-0026 StageDescriptor 答 "What is this Stage?"**
> **ADR-0027 RuntimeMetadata 答 "What happened during execution?"**
> **ADR-0028 Metadata Access API 答 "How do I read runtime state uniformly?"**
> **ADR-0029 Stage Registry 答 "Where do I find a Stage?"**
> **ADR-0030 Registry Introspection 答 "What does the Registry contain?"**
> **本 ADR 答 "How do I serialize all metadata uniformly for external consumers?"**

---

## 1. 背景与目标

### 1.1 背景

V1.0.6 - V1.0.9 引入了 4 个独立 metadata 类型:
- `StageDescriptor` (V1.0.6, frozen dataclass) — Stage 静态身份
- `RuntimeMetadata` (V1.0.7, mutable dataclass) — 运行时状态
- `StageInfo` (V1.0.9, frozen dataclass) — Registry 上下文信息
- `ConditionEval` (V1.0.4, embedded in RuntimeMetadata) — 条件求值结果

当前序列化状况（碎片化）:
- `StageDescriptor`: 无 `to_dict()`，外部消费者需手动 dict literal
- `RuntimeMetadata`: 无 `to_dict()`，仅 `ConditionEval.to_dict()` 存在
- `StageInfo`: 通过 `StageRegistry.to_dict()` 间接序列化（嵌入 `_descriptor_to_dict` helper）
- `_descriptor_to_dict`: V1.0.9 helper 在 `stage_registry.py` 模块级，**位置错误**（应放序列化层）

**当前痛点**:
1. **序列化逻辑分散**: `_descriptor_to_dict` 在 stage_registry.py，`ConditionEval.to_dict` 在 condition_stage.py，缺统一入口
2. **StageDescriptor 无 to_dict()**: CLI / MCP / WebUI 消费 StageDescriptor 时需重复实现
3. **RuntimeMetadata 无 to_dict()**: 序列化运行时状态需手动构造 dict
4. **无 schema 稳定性约定**: 不同消费者可能产生不同 schema
5. **V1.0.9 `_descriptor_to_dict` 位置违反 SRP**: stage_registry.py 不应负责 StageDescriptor 序列化

### 1.2 目标（V1.0.10 Metadata Serialization）

V1.0.10 在**不破坏 V1.0.6 - V1.0.9 API** 的前提下，建立统一序列化层:

1. **新建 `planner/metadata_serialization.py` 模块**:
   - `serialize_descriptor(d: StageDescriptor) -> Dict[str, Any]`
   - `serialize_stage_info(info: StageInfo) -> Dict[str, Any]`
   - `serialize_runtime_metadata(rm: RuntimeMetadata) -> Dict[str, Any]`
   - `serialize_condition_eval(ce: ConditionEval) -> Dict[str, Any]`
   - `to_json(d: dict, *, indent: Optional[int] = 2) -> str` (通用 JSON 序列化)

2. **StageDescriptor / StageInfo 增加 `to_dict()` 方法** (frozen dataclass 可加方法，不破坏不可变性):
   - `StageDescriptor.to_dict() -> Dict[str, Any]` — delegate to `serialize_descriptor`
   - `StageInfo.to_dict() -> Dict[str, Any]` — delegate to `serialize_stage_info`
   - `RuntimeMetadata.to_dict() -> Dict[str, Any]` — delegate to `serialize_runtime_metadata`

3. **迁移 `_descriptor_to_dict` 到序列化模块**:
   - `stage_registry._descriptor_to_dict` 改为 delegate to `serialize_descriptor`
   - 保留 `_descriptor_to_dict` 作为 V1.0.9 backward compat (deprecated 内部使用)

4. **`StageRegistry.to_dict()` 重构**:
   - 用 `serialize_descriptor` + `serialize_stage_info` 替代 `_descriptor_to_dict` 内联
   - 保持 schema 不变 (R4 stability test 守护)

5. **不引入 `schema_version`** (ChatGPT V1.0.9 review M1 deferred to V1.1):
   - V1.0.10 保持现有 schema (R4 stability test 锁定 keys)
   - V1.1 评估: `{"schema_version": 1, "stages": [...]}`

6. **不引入 UTC timestamp** (ChatGPT V1.0.9 review M2 deferred to V1.1):
   - V1.0.10 保留 `datetime.now()` (naive)
   - V1.1 评估: `datetime.now(timezone.utc)` for distributed registry

7. **不破坏 V1.0.6 - V1.0.9**:
   - 所有现有 API 保持不变
   - `StageRegistry.to_dict()` schema 保持不变 (R4 test 守护)
   - 现有测试无需修改

### 1.3 非目标

- ❌ **不**做 Pipeline Introspection (V1.0.11 评估)
- ❌ **不**做 Predicate API (V1.0.11 评估)
- ❌ **不**做 CLI Introspection (V1.0.12 评估, 依赖本 ADR)
- ❌ **不**做 schema_version (V1.1, ChatGPT M1 deferred)
- ❌ **不**做 UTC timestamp (V1.1, ChatGPT M2 deferred)
- ❌ **不**做 remote / distributed Registry (V2)
- ❌ **不**做 metadata persistence (跨进程)
- ❌ **不**做 metadata versioning (多版本共存)
- ❌ **不**改 StageDescriptor / RuntimeMetadata / StageInfo 字段定义 (V1.0.6/V1.0.7/V1.0.9 已稳定)
- ❌ **不**做 Registry persistence (跨进程) — 序列化仅用于 inspection / debug / external consumer, 不用于状态恢复
- ❌ **不**做 YAML / TOML / MsgPack 等其他格式 (V1.0.10 仅 JSON / dict)

---

## 2. 设计

### 2.1 `planner/metadata_serialization.py` 模块

```python
# planner/metadata_serialization.py (V1.0.10 NEW)
"""Metadata Serialization Layer (V1.0.10, ADR-0031).

统一序列化:
  - StageDescriptor (V1.0.6)
  - StageInfo (V1.0.9)
  - RuntimeMetadata (V1.0.7)
  - ConditionEval (V1.0.4)

设计原则 (ChatGPT V1.0.9 代码审核 Q6 推荐):
  - 序列化逻辑集中在 metadata_serialization.py (SRP)
  - dataclass.to_dict() 方法 delegate 到此模块
  - schema stability test 守护 keys 不变

Non-goal (V1.0.10):
  - 不引入 schema_version (V1.1)
  - 不引入 UTC timestamp (V1.1)
  - 不做 YAML / TOML / MsgPack
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from planner.stage_descriptor import StageDescriptor
from planner.runtime_metadata import RuntimeMetadata
from planner.stage_registry import StageInfo
from planner.stages.condition_stage import ConditionEval


# ─────────────────────────────────────────────────────────────
# Schema 版本占位 (V1.1 启用, ChatGPT M1 deferred)
# ─────────────────────────────────────────────────────────────
# V1.0.10: 不启用 schema_version (避免破坏 V1.0.9 R4 stability test)
# V1.1: 评估在 to_dict() 顶层加 "schema_version": 1
METADATA_SCHEMA_VERSION: Optional[int] = None  # V1.1 启用


# ─────────────────────────────────────────────────────────────
# StageDescriptor → dict
# ─────────────────────────────────────────────────────────────
def serialize_descriptor(d: StageDescriptor) -> Dict[str, Any]:
    """序列化 StageDescriptor 为 dict (V1.0.10).

    Schema (V1.0.10 stable, R4 守护):
      {
        "name": str,
        "role": str,
        "version": int,
        "capabilities": List[str],  # sorted
        "idempotent": bool,
        "has_side_effects": bool,
        "always_run_after_stop": bool,
        "experimental": bool,
        "description": str,
        "owner": str,
      }

    Args:
        d: StageDescriptor 实例

    Returns:
        dict (按字段名字典序无关, 但 capabilities sorted for determinism)

    Migration:
      - V1.0.9: stage_registry._descriptor_to_dict (模块级 helper)
      - V1.0.10: 迁移到此函数 (stage_registry 保留 deprecated alias)
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


# ─────────────────────────────────────────────────────────────
# StageInfo → dict
# ─────────────────────────────────────────────────────────────
def serialize_stage_info(info: StageInfo) -> Dict[str, Any]:
    """序列化 StageInfo 为 dict (V1.0.10).

    Schema (V1.0.10 stable):
      {
        "name": str,                          # info.descriptor.name
        "descriptor": {...},                  # serialize_descriptor(info.descriptor)
        "source": str,                        # "builtin" | "third_party" | "test"
        "requires": List[str],                # list(info.requires)
        "registered_at": str | None,          # ISO format or None
      }

    Args:
        info: StageInfo 实例

    Returns:
        dict
    """
    return {
        "name": info.descriptor.name,
        "descriptor": serialize_descriptor(info.descriptor),
        "source": info.source,
        "requires": list(info.requires),
        "registered_at": info.registered_at.isoformat() if info.registered_at else None,
    }


# ─────────────────────────────────────────────────────────────
# RuntimeMetadata → dict
# ─────────────────────────────────────────────────────────────
def serialize_runtime_metadata(rm: RuntimeMetadata) -> Dict[str, Any]:
    """序列化 RuntimeMetadata 为 dict (V1.0.10).

    Schema (V1.0.10 stable):
      {
        "server_metrics": Dict[str, Any],
        "condition_eval": Dict[str, Any] | None,  # serialize_condition_eval or None
        "stopped_by": str | None,
        "plan": Dict[str, int],
        "custom": Dict[str, Any],
      }

    Args:
        rm: RuntimeMetadata 实例

    Returns:
        dict

    Note:
      - condition_eval 嵌套用 serialize_condition_eval
      - server_metrics / plan / custom 直接 dump (Dict[str, Any])
      - V1.0.10 不引入 schema_version (V1.1 评估)
    """
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


# ─────────────────────────────────────────────────────────────
# ConditionEval → dict
# ─────────────────────────────────────────────────────────────
def serialize_condition_eval(ce: ConditionEval) -> Dict[str, Any]:
    """序列化 ConditionEval 为 dict (V1.0.10).

    Migration:
      - V1.0.4: ConditionEval.to_dict() method (in condition_stage.py)
      - V1.0.10: 迁移到序列化模块 (ConditionEval.to_dict 保留 backward compat)

    Schema (V1.0.4 stable, V1.0.10 不变):
      {
        "stage": str,
        "condition_name": str,
        "result": bool,
        "action": str,
        "timestamp": str | None,    # ISO format or None
        "stopped_by": str | None,
      }
    """
    return {
        "stage": ce.stage,
        "condition_name": ce.condition_name,
        "result": ce.result,
        "action": ce.action,
        "timestamp": ce.timestamp,
        "stopped_by": ce.stopped_by,
    }


# ─────────────────────────────────────────────────────────────
# Generic JSON helper
# ─────────────────────────────────────────────────────────────
def to_json(d: Dict[str, Any], *, indent: Optional[int] = 2) -> str:
    """通用 dict → JSON 字符串 (V1.0.10).

    Args:
        d: 已序列化的 dict (来自 serialize_*)
        indent: JSON 缩进 (None = 紧凑)

    Returns:
        JSON 字符串 (UTF-8, ensure_ascii=False)
    """
    return json.dumps(d, indent=indent, ensure_ascii=False)


__all__ = [
    "METADATA_SCHEMA_VERSION",
    "serialize_descriptor",
    "serialize_stage_info",
    "serialize_runtime_metadata",
    "serialize_condition_eval",
    "to_json",
]
```

### 2.2 `StageDescriptor` 增加 `to_dict()` 方法 (V1.0.6 → V1.0.10 扩展)

```python
# planner/stage_descriptor.py (V1.0.10 扩展, V1.0.6 API 兼容)
@dataclass(frozen=True)
class StageDescriptor:
    # ... (V1.0.6 字段不变)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict (V1.0.10, ADR-0031).

        Delegate to `planner.metadata_serialization.serialize_descriptor`.

        Returns:
            dict (schema 见 ADR-0031 §2.1)
        """
        from planner.metadata_serialization import serialize_descriptor
        return serialize_descriptor(self)
```

**Why 方法而非 helper**: frozen dataclass 可加方法（不破坏不可变性）。`to_dict()` 是 metadata 类型的自然 API (类似 `dataclasses.asdict` 但 schema 显式控制)。

**Why delegate**: 集中序列化逻辑到 `metadata_serialization.py` (SRP)，`StageDescriptor.to_dict()` 仅作为 convenience API。

**Why lazy import**: 避免 `stage_descriptor.py` → `metadata_serialization.py` → `stage_descriptor.py` 循环依赖（V1.0.6 已用 TYPE_CHECKING 处理过 pipeline 循环，这里同模式）。

### 2.3 `StageInfo` 增加 `to_dict()` 方法 (V1.0.9 → V1.0.10 扩展)

```python
# planner/stage_registry.py (V1.0.10 扩展, V1.0.9 API 兼容)
@dataclass(frozen=True)
class StageInfo:
    # ... (V1.0.9 字段不变)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict (V1.0.10, ADR-0031).

        Delegate to `planner.metadata_serialization.serialize_stage_info`.
        """
        from planner.metadata_serialization import serialize_stage_info
        return serialize_stage_info(self)
```

### 2.4 `RuntimeMetadata` 增加 `to_dict()` 方法 (V1.0.7 → V1.0.10 扩展)

```python
# planner/runtime_metadata.py (V1.0.10 扩展, V1.0.7 API 兼容)
@dataclass
class RuntimeMetadata:
    # ... (V1.0.7 字段不变)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict (V1.0.10, ADR-0031).

        Delegate to `planner.metadata_serialization.serialize_runtime_metadata`.

        Note:
          - condition_eval 嵌套序列化
          - 不包含 schema_version (V1.1 评估)
        """
        from planner.metadata_serialization import serialize_runtime_metadata
        return serialize_runtime_metadata(self)
```

### 2.5 `ConditionEval.to_dict()` 迁移到 delegate (V1.0.4 → V1.0.10 backward compat)

```python
# planner/stages/condition_stage.py (V1.0.10 backward compat)
@dataclass
class ConditionEval:
    # ... (V1.0.4 字段不变)

    def to_dict(self) -> dict:
        """序列化为 dict (V1.0.4 → V1.0.10 delegate).

        V1.0.10: 迁移逻辑到 metadata_serialization.serialize_condition_eval
        V1.0.4 行为: 保持不变 (backward compat)
        """
        from planner.metadata_serialization import serialize_condition_eval
        return serialize_condition_eval(self)
```

### 2.6 `stage_registry._descriptor_to_dict` 改为 deprecated alias

```python
# planner/stage_registry.py (V1.0.10 deprecated alias)
def _descriptor_to_dict(d: StageDescriptor) -> Dict[str, Any]:
    """StageDescriptor → dict (V1.0.9 helper, V1.0.10 deprecated).

    V1.0.10: 迁移到 `planner.metadata_serialization.serialize_descriptor`.
    此函数保留作为 V1.0.9 backward compat (内部使用).

    Deprecated:
      - V1.0.10: 用 `StageDescriptor.to_dict()` 或 `serialize_descriptor()` 替代
      - V1.1: 删除此 helper
    """
    from planner.metadata_serialization import serialize_descriptor
    return serialize_descriptor(d)
```

### 2.7 `StageRegistry.to_dict()` 重构 (用新序列化模块)

```python
# planner/stage_registry.py (V1.0.10 重构, schema 不变)
def to_dict(self) -> Dict[str, Any]:
    """序列化 Registry 状态为 dict (V1.0.9, V1.0.10 重构).

    V1.0.10 重构: 用 serialize_stage_info 替代内联 _descriptor_to_dict
    Schema 保持 V1.0.9 (R4 stability test 守护)

    Returns:
        {
            "stages": [serialize_stage_info(info) for info in self._info.values()],
            "roles": sorted(self.roles()),
            "capabilities": sorted(self.capabilities()),
            "default_order": list(self.default_order()),
        }
    """
    from planner.metadata_serialization import serialize_stage_info
    return {
        "stages": [serialize_stage_info(info) for info in self._info.values()],
        "roles": sorted(self.roles()),
        "capabilities": sorted(self.capabilities()),
        "default_order": list(self.default_order()),
    }
```

### 2.8 使用示例

```python
# V1.0.10 序列化示例
from planner.stage_descriptor import StageDescriptor
from planner.stage_registry import StageInfo, default_registry
from planner.runtime_metadata import RuntimeMetadata
from planner.metadata_serialization import (
    serialize_descriptor,
    serialize_stage_info,
    serialize_runtime_metadata,
    to_json,
)

# 1. StageDescriptor → dict / JSON
d = StageDescriptor(name="route", role="stage", capabilities=frozenset({"selects_provider"}))
print(d.to_dict())                # V1.0.10 method
print(serialize_descriptor(d))    # V1.0.10 module function
print(to_json(d.to_dict()))       # V1.0.10 JSON helper

# 2. StageInfo → dict / JSON
info = default_registry().info("route")
print(info.to_dict())             # V1.0.10 method
print(serialize_stage_info(info)) # V1.0.10 module function

# 3. RuntimeMetadata → dict / JSON
rm = RuntimeMetadata()
rm.stopped_by = "condition"
print(rm.to_dict())               # V1.0.10 method
print(serialize_runtime_metadata(rm))

# 4. StageRegistry → dict (V1.0.9 API, V1.0.10 内部重构)
print(default_registry().to_dict())
print(default_registry().to_json())
```

---

## 3. 关键设计决策

### 3.1 序列化模块独立 vs 嵌入各 dataclass

**采纳**: 独立模块 `planner/metadata_serialization.py` + dataclass.to_dict() delegate

**Rejected alternatives**:
- ❌ **各 dataclass 自带 to_dict() (无独立模块)**: 序列化逻辑分散，难以统一管理 schema_version / UTC timestamp 等横切关注点
- ❌ **仅独立模块 (无 dataclass.to_dict)**: API 不直观 (`serialize_descriptor(d)` vs `d.to_dict()`)
- ❌ **JSON encoder class**: 用 `json.dumps(d, cls=MetadataEncoder)` — 过度抽象，难以调试

### 3.2 `to_dict()` 方法 vs helper function (双 API)

**采纳**: 双 API — dataclass.to_dict() (convenience) + serialize_xxx() (functional)

**Why**:
- `d.to_dict()` 面向用户 (Pythonic, 类似 stdlib `dataclasses.asdict`)
- `serialize_descriptor(d)` 面向框架 (functional, 易组合, 易测试)
- 两者 delegate 到同一逻辑 (DRY)

**Rejected**:
- ❌ 仅 `to_dict()` 方法: 不利于 functional composition (e.g. `[serialize_descriptor(d) for d in descriptors]` 比 `[d.to_dict() for d in descriptors]` 更明确)

### 3.3 不引入 `schema_version` (V1.1 deferred)

**采纳**: V1.0.10 不引入 `schema_version`

**Why** (ChatGPT V1.0.9 review M1):
- 当前 schema 已被 V1.0.9 R4 stability test 锁定 (keys 不变)
- 引入 `schema_version` 会破坏 R4 test (顶层 keys 增加 `"schema_version"`)
- V1.1 评估: 在 to_dict() 顶层加 `"schema_version": 1`, 同时更新 R4 test

**V1.0.10 占位**: `METADATA_SCHEMA_VERSION: Optional[int] = None` (V1.1 启用为 `1`)

### 3.4 不引入 UTC timestamp (V1.1 deferred)

**采纳**: V1.0.10 保留 `datetime.now()` (naive datetime)

**Why** (ChatGPT V1.0.9 review M2):
- V1.0.x Registry 是单进程，naive datetime 足够
- 引入 UTC 需改 `StageInfo.registered_at` 默认值 (V1.0.9 R3 已稳定)
- V1.1 评估: `datetime.now(timezone.utc)` for distributed registry / audit log

### 3.5 lazy import 避免循环依赖

**采纳**: `to_dict()` 方法内 lazy import `metadata_serialization`

**Why**:
- `stage_descriptor.py` (V1.0.6) → `metadata_serialization.py` (V1.0.10) → `stage_descriptor.py` 循环
- V1.0.6 已用 TYPE_CHECKING 处理过 pipeline 循环，这里同模式
- lazy import 在方法内 (而非模块顶层) 避免启动时循环

### 3.6 `ConditionEval.to_dict()` 保留 backward compat

**采纳**: V1.0.4 `ConditionEval.to_dict()` 保留，V1.0.10 改为 delegate 到 `serialize_condition_eval`

**Why**:
- V1.0.4 API 已稳定 (被 RuntimeMetadata.set_condition_eval 调用)
- V1.0.10 不应破坏 V1.0.4 API
- 迁移路径: V1.0.10 delegate → V1.1 评估是否移除 method

---

## 4. API 演进路径

```
V1.0.4: ConditionEval.to_dict()                              [Stable]
V1.0.6: StageDescriptor (frozen dataclass, no to_dict)        [Stable]
V1.0.7: RuntimeMetadata (mutable dataclass, no to_dict)       [Stable]
V1.0.9: StageInfo + _descriptor_to_dict (helper in registry)  [Stable]
V1.0.10: metadata_serialization.py + to_dict() methods        [本 ADR]
V1.1:   schema_version + UTC timestamp (M1+M2 deferred)       [Future]
V2:     YAML / TOML / MsgPack / metadata versioning           [Future]
```

---

## 5. Rejected Alternatives

### 5.1 ❌ StageDescriptor 自带 to_dict() 无独立模块

**Rejected**: 序列化逻辑分散在各 dataclass，难以统一管理。

**Why**: 未来加 schema_version / UTC timestamp / field filtering 需改多处。

### 5.2 ❌ 用 `dataclasses.asdict()` 替代自定义 to_dict()

**Rejected**: `dataclasses.asdict()` 递归转 dict，但:
- 不控制 schema (字段顺序 / 包含 / 排除)
- 不处理 frozenset → list 转换 (capabilities 是 FrozenSet[str])
- 不处理 datetime → ISO string 转换 (registered_at)
- 不利于 schema stability test

### 5.3 ❌ JSON encoder class `json.dumps(d, cls=MetadataEncoder)`

**Rejected**: 过度抽象。
- 难以调试 (encoder 内部逻辑不透明)
- 难以扩展 (subclass encoder)
- 难以测试 (需 JSON round-trip)

### 5.4 ❌ 在 V1.0.10 引入 schema_version

**Rejected** (ChatGPT M1 deferred): V1.0.9 R4 stability test 锁定的 schema 不应破坏。V1.1 评估时统一更新 R4 test + 加 schema_version。

### 5.5 ❌ 在 V1.0.10 引入 UTC timestamp

**Rejected** (ChatGPT M2 deferred): V1.0.x 单进程 Registry naive datetime 足够。V1.1 distributed registry 时再改。

### 5.6 ❌ 把序列化逻辑放 `planner/__init__.py`

**Rejected**: `planner/__init__.py` 应保持 minimal (避免 import side-effect)。序列化逻辑应在独立模块。

### 5.7 ❌ 用 `pydantic` / `marshmallow` 等序列化库

**Rejected**: V1.0.x 保持零外部依赖 (dataclass + json 标准库足够)。V2 评估 pydantic v2 / msgspec。

---

## 6. 测试策略

### 6.1 测试文件: `tests/test_metadata_serialization.py` (~30 tests)

**测试类**:

1. **TestSerializeDescriptor** (6 tests)
   - `test_serialize_descriptor_returns_dict`
   - `test_serialize_descriptor_capabilities_sorted`
   - `test_serialize_descriptor_all_fields_present`
   - `test_serialize_descriptor_field_types`
   - `test_serialize_descriptor_immutable_input` (序列化不修改原 dataclass)
   - `test_serialize_descriptor_schema_stable` (R4 守护: keys 不变)

2. **TestSerializeStageInfo** (5 tests)
   - `test_serialize_stage_info_returns_dict`
   - `test_serialize_stage_info_includes_descriptor`
   - `test_serialize_stage_info_registered_at_iso`
   - `test_serialize_stage_info_registered_at_none` (防御)
   - `test_serialize_stage_info_schema_stable` (R4 守护)

3. **TestSerializeRuntimeMetadata** (5 tests)
   - `test_serialize_runtime_metadata_returns_dict`
   - `test_serialize_runtime_metadata_condition_eval_none`
   - `test_serialize_runtime_metadata_condition_eval_present`
   - `test_serialize_runtime_metadata_custom_namespace`
   - `test_serialize_runtime_metadata_schema_stable`

4. **TestSerializeConditionEval** (3 tests)
   - `test_serialize_condition_eval_returns_dict`
   - `test_serialize_condition_eval_all_fields`
   - `test_serialize_condition_eval_backward_compat` (V1.0.4 API)

5. **TestToDictMethods** (6 tests, V1.0.10 新增方法)
   - `test_stage_descriptor_to_dict` (StageDescriptor.to_dict())
   - `test_stage_info_to_dict` (StageInfo.to_dict())
   - `test_runtime_metadata_to_dict` (RuntimeMetadata.to_dict())
   - `test_condition_eval_to_dict` (ConditionEval.to_dict() V1.0.4 backward compat)
   - `test_to_dict_delegates_to_serialize` (一致性)
   - `test_to_dict_methods_idempotent`

6. **TestToJsonHelper** (3 tests)
   - `test_to_json_default_indent`
   - `test_to_json_compact` (indent=None)
   - `test_to_json_ensure_ascii_false`

7. **TestMigrationFromV109** (3 tests, 迁移正确性)
   - `test_descriptor_to_dict_alias_delegates` (V1.0.9 helper 仍工作)
   - `test_stage_registry_to_dict_uses_serialize_stage_info` (V1.0.9 schema 不变)
   - `test_stage_registry_to_dict_schema_stable` (R4 守护 V1.0.9 → V1.0.10)

8. **TestSchemaStability** (2 tests, 跨版本稳定)
   - `test_metadata_schema_version_none_v1010` (V1.1 启用后此 test 更新)
   - `test_no_schema_version_in_v1010_output` (确认 V1.0.10 不引入)

### 6.2 回归测试 (V1.0.6 - V1.0.9)

- V1.0.6 test_stage_descriptor.py: 全部通过 (to_dict() 不破坏 frozen)
- V1.0.7 test_runtime_metadata.py: 全部通过 (to_dict() 不破坏 write-through helper)
- V1.0.8 test_metadata_access_api.py: 全部通过
- V1.0.9 test_stage_registry_introspection.py: 全部通过 (R4 stability test 守护 schema)

### 6.3 性能测试 (可选)

- `serialize_descriptor(d)` < 1µs (单次)
- `serialize_stage_info(info)` < 2µs (含嵌套 descriptor)
- `serialize_runtime_metadata(rm)` < 5µs (含嵌套 condition_eval)

---

## 7. 实施计划

### 7.1 阶段 1: 新建 `planner/metadata_serialization.py` (本 ADR)

```python
# 新建模块, 5 个公开 API:
- METADATA_SCHEMA_VERSION: Optional[int] = None  (V1.1 启用)
- serialize_descriptor(d) -> dict
- serialize_stage_info(info) -> dict
- serialize_runtime_metadata(rm) -> dict
- serialize_condition_eval(ce) -> dict
- to_json(d, *, indent=2) -> str
```

### 7.2 阶段 2: 各 dataclass 加 `to_dict()` 方法

- `StageDescriptor.to_dict()` (V1.0.6 → V1.0.10)
- `StageInfo.to_dict()` (V1.0.9 → V1.0.10)
- `RuntimeMetadata.to_dict()` (V1.0.7 → V1.0.10)
- `ConditionEval.to_dict()` (V1.0.4 → V1.0.10 delegate, 保留 method)

### 7.3 阶段 3: 迁移 `stage_registry._descriptor_to_dict`

- V1.0.9 helper 改为 delegate to `serialize_descriptor`
- 保留函数 (V1.0.9 backward compat, V1.1 删除)

### 7.4 阶段 4: 重构 `StageRegistry.to_dict()`

- 用 `serialize_stage_info` 替代内联 `_descriptor_to_dict`
- V1.0.9 R4 stability test 守护 schema 不变

### 7.5 阶段 5: 测试 + 回归

- 新增 ~30 tests (test_metadata_serialization.py)
- V1.0.6 - V1.0.9 全部回归通过 (398 + 30 ≈ 428 tests)

---

## 8. V1.0.11 演化规划

### 8.1 V1.1 评估 (ChatGPT M1+M2 deferred)

- **schema_version**: `{"schema_version": 1, "stages": [...]}`
- **UTC timestamp**: `datetime.now(timezone.utc)`
- **source Enum**: V1.0.9 R2 deferred → V1.1 严格 Enum

### 8.2 V1.0.11 候选 ADR

- **ADR-0032 Pipeline Introspection (SHOULD)**: `pipeline.describe()` / `pipeline.graph()`
- **ADR-0033 Predicate API (SHOULD)**: `find(role=, capability=, requires=, source=)` 统一查询
- **ADR-0034 CLI Introspection (MAY)**: `ai-hub stage list / info / dump` CLI commands

### 8.3 V2 评估

- pydantic v2 / msgspec 替代 dataclass
- YAML / TOML / MsgPack 序列化格式
- metadata versioning (多版本共存)
- remote / distributed Registry

---

## 9. Open Questions (for ChatGPT)

**Q1: 序列化模块位置**
`planner/metadata_serialization.py` 是否是最佳位置? 还是:
- (a) `planner/metadata/serialization.py` (子包)
- (b) `planner/serialize.py` (短名)
- (c) `planner/metadata.py` (但 V1.0.7 已用 runtime_metadata.py)

**Q2: to_dict() 方法 vs helper function 双 API**
当前设计 dataclass.to_dict() + serialize_xxx() 双 API delegate 同一逻辑。是否过设计? 还是只保留一种?

**Q3: StageDescriptor.to_dict() 破坏 V1.0.6 Core Freeze?**
V1.0.6 StageDescriptor 已 Accepted 9.95/10。V1.0.10 加 `to_dict()` 方法是否算 "破坏 Core Freeze"? (方法不改变字段, 不破坏 frozen)

**Q4: lazy import 是否合理?**
`to_dict()` 方法内 `from planner.metadata_serialization import serialize_descriptor` lazy import。是否应该:
- (a) 模块顶层 import (可能有循环)
- (b) TYPE_CHECKING + lazy import (当前方案)
- (c) 反转依赖 (metadata_serialization 不 import StageDescriptor, 用 Protocol)

**Q5: ConditionEval.to_dict() 保留还是移除?**
V1.0.4 `ConditionEval.to_dict()` 已存在。V1.0.10 改为 delegate。是否:
- (a) 保留 method (backward compat)
- (b) 移除 method, 仅用 `serialize_condition_eval()` (functional)
- (c) 保留 + DeprecationWarning

**Q6: RuntimeMetadata.to_dict() 包含 ctx.metadata 兼容字段?**
RuntimeMetadata 是 V1.0.7 强类型, ctx.metadata 是 V1.0.6 dict 兼容。`rm.to_dict()` 应该:
- (a) 仅包含 RuntimeMetadata 字段 (当前方案)
- (b) 合并 ctx.metadata 兼容字段 (但需要 ctx 引用)
- (c) 提供两个 API: `to_dict()` (RuntimeMetadata) + `to_full_dict(ctx)` (合并)

**Q7: serialize_xxx 函数签名是否要 schema_version 参数?**
```python
def serialize_descriptor(d, *, schema_version: Optional[int] = None) -> dict:
```
还是 V1.0.10 不加, V1.1 评估时再加?

**Q8: 测试覆盖盲点**
~30 tests 是否够? 关键场景:
- (a) 嵌套序列化 (StageInfo → StageDescriptor)
- (b) 字段顺序 (dict 顺序 = Python 3.7+ insertion order)
- (c) frozenset → sorted list (deterministic)
- (d) datetime → ISO string
- (e) None 字段处理
- (f) 跨版本 schema stability (R4 守护)

---

## 10. Review Focus (for ChatGPT)

请评估以下 8 个维度 (1-10 评分 + 简短评价):

1. **架构方向** — 序列化模块独立 vs 嵌入各 dataclass 的选择是否正确?
2. **API 一致性** — `to_dict()` 方法 + `serialize_xxx()` helper 双 API 是否合理?
3. **向后兼容** — V1.0.6/V1.0.7/V1.0.9 加 `to_dict()` 方法是否破坏 Core Freeze?
4. **数据结构** — schema 稳定性 + R4 stability test 策略
5. **替代方案质量** — Rejected alternatives (5.1-5.7) 是否合理?
6. **测试策略** — ~30 tests / 8 classes 覆盖 + R4 stability 守护
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


---

# PART 2: ChatGPT Review Prompt

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

