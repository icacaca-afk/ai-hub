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
    "to_json",
]
