# AI Hub — Metadata Serialization Layer (V1.0.10, ADR-0031)
#
# 统一序列化:
#   - StageDescriptor (V1.0.6)
#   - StageInfo (V1.0.9)
#   - RuntimeMetadata (V1.0.7)
#   - ConditionEval (V1.0.4)
#
# 设计原则 (ChatGPT V1.0.9 代码审核 Q6 推荐):
#   - 序列化逻辑集中在 metadata_serialization.py (SRP)
#   - dataclass.to_dict() 方法 delegate 到此模块
#   - schema stability test 守护 keys 不变
#
# R1 (ChatGPT 9.6/10 Blocking-2 采纳):
#   serialize_xxx() 是 canonical serialization implementation,
#   to_dict() methods 仅是 facade (convenience wrapper).
#
# Non-goal (V1.0.10):
#   - 不引入 schema_version (V1.1)
#   - 不引入 UTC timestamp (V1.1)
#   - 不做 YAML / TOML / MsgPack
#
# API Stability: Experimental

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from planner.stage_descriptor import StageDescriptor
from planner.runtime_metadata import RuntimeMetadata
from planner.stage_registry import StageInfo
from planner.stages.condition_stage import ConditionEval
from planner.pipeline_descriptor import PipelineDescriptor
from planner.predicate_descriptor import PredicateDescriptor


# ─────────────────────────────────────────────────────────────
# Schema 版本占位 (V1.1 启用, ChatGPT M1 deferred)
# ─────────────────────────────────────────────────────────────
# V1.0.10: 不启用 schema_version (避免破坏 V1.0.9 R4 stability test)
# V1.1: 评估在 to_dict() 顶层加 "schema_version": 1
# R2 (ChatGPT 9.6/10): 重命名 METADATA_SCHEMA_VERSION → FUTURE_METADATA_SCHEMA_VERSION
FUTURE_METADATA_SCHEMA_VERSION: Optional[int] = None  # V1.1 启用为 1


# ─────────────────────────────────────────────────────────────
# StageDescriptor → dict (canonical)
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
        dict (capabilities sorted for determinism)
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
# StageInfo → dict (canonical)
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
    """
    return {
        "name": info.descriptor.name,
        "descriptor": serialize_descriptor(info.descriptor),
        "source": info.source,
        "requires": list(info.requires),
        "registered_at": info.registered_at.isoformat() if info.registered_at else None,
    }


# ─────────────────────────────────────────────────────────────
# RuntimeMetadata → dict (canonical)
# ─────────────────────────────────────────────────────────────
def serialize_runtime_metadata(rm: RuntimeMetadata) -> Dict[str, Any]:
    """序列化 RuntimeMetadata 为 dict (V1.0.10).

    Schema (V1.0.10 stable):
      {
        "server_metrics": Dict[str, Any],
        "condition_eval": Dict[str, Any] | None,
        "stopped_by": str | None,
        "plan": Dict[str, int],
        "custom": Dict[str, Any],
      }
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
# ConditionEval → dict (canonical)
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
        "timestamp": float,
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
# PredicateDescriptor → dict (canonical, V1.0.12 ADR-0033)
# ─────────────────────────────────────────────────────────────
def serialize_predicate(pd: PredicateDescriptor) -> Dict[str, Any]:
    """Serialize explicit predicate semantics without inspecting a callable."""
    return {
        "name": pd.name,
        "description": pd.description,
        "subject": pd.subject,
    }


# ─────────────────────────────────────────────────────────────
# PipelineDescriptor → dict (canonical, V1.0.11 ADR-0032)
# ─────────────────────────────────────────────────────────────
def serialize_pipeline(pd: PipelineDescriptor) -> Dict[str, Any]:
    """序列化 PipelineDescriptor 为 dict (V1.0.11 ADR-0032).

    MUST consume PipelineDescriptor, NOT ExecutionPipeline.
    这是单向转换链的硬约束 (ADR-0032 §2.2 Architecture Invariant).

    Schema (V1.0.11):
      {
        "name": str,
        "stages": List[Dict],   # {id, name, role, position, index}
        "edges": List[Dict],    # {from, to, type} — from/to 引用 stage id
        "has_router": bool,
        "has_quota": bool,
        "has_hooks": bool,
      }

    Bridge 作为 virtual node 包含在 stages 中 (graph closure).
    每个 stage 包含稳定结构 id (pre:0, bridge, post:0 等).
    """
    stages: list = []
    edges: list = []

    # Pre-bridge stages
    for i, sd in enumerate(pd.pre_bridge):
        stages.append({
            "id": f"pre:{i}",
            "name": sd.name,
            "role": sd.role,
            "position": "pre",
            "index": i,
        })

    # Bridge virtual node (P0: graph closure)
    bridge_id = "bridge"
    stages.append({
        "id": bridge_id,
        "name": "__bridge__",
        "role": "bridge",
        "position": "bridge",
        "index": -1,
    })

    # Post-bridge stages
    for i, sd in enumerate(pd.post_bridge):
        stages.append({
            "id": f"post:{i}",
            "name": sd.name,
            "role": sd.role,
            "position": "post",
            "index": i,
        })

    # Edges: pre → bridge
    if pd.pre_bridge:
        last_pre_id = f"pre:{len(pd.pre_bridge) - 1}"
        edges.append({"from": last_pre_id, "to": bridge_id, "type": "pre_to_bridge"})

    # Edges: bridge → post
    if pd.post_bridge:
        edges.append({"from": bridge_id, "to": "post:0", "type": "bridge_to_post"})

    # Edges: sequential within post
    for i in range(1, len(pd.post_bridge)):
        edges.append({"from": f"post:{i - 1}", "to": f"post:{i}", "type": "sequential"})

    # Edges: sequential within pre (if multiple pre stages)
    for i in range(1, len(pd.pre_bridge)):
        edges.append({"from": f"pre:{i - 1}", "to": f"pre:{i}", "type": "sequential"})

    return {
        "name": pd.name,
        "stages": stages,
        "edges": edges,
        "has_router": pd.has_router,
        "has_quota": pd.has_quota,
        "has_hooks": pd.has_hooks,
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
    "FUTURE_METADATA_SCHEMA_VERSION",
    "serialize_descriptor",
    "serialize_stage_info",
    "serialize_runtime_metadata",
    "serialize_condition_eval",
    "serialize_predicate",
    "serialize_pipeline",
    "to_json",
]
