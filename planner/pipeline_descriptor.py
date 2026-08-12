# AI Hub — PipelineDescriptor
# V1.0.11: Pipeline 结构描述 (ADR-0032 ChatGPT 9.4/10 Conditional Approve)
#
# PipelineDescriptor 是什么:
#   - Pipeline 的静态结构快照 (immutable snapshot)
#   - 描述: pre_bridge stages / post_bridge stages / 配置标志
#   - 与 ExecutionPipeline 解耦 (describe() 产生快照, 之后 Pipeline 变化不影响快照)
#
# 关键设计原则 (ADR-0032):
#   ① frozen=True 不可变 (与 StageDescriptor / RuntimeMetadata 一致)
#   ② Tuple 而非 List (不可变 + hashable)
#   ③ version 是 producer/API version, 不是 schema_version (V1.1 deferred)
#   ④ 单向转换链: ExecutionPipeline → PipelineDescriptor → dict → JSON
#
# API Stability: Experimental

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from planner.stage_descriptor import StageDescriptor


@dataclass(frozen=True)
class PipelineDescriptor:
    """Pipeline 结构描述（不可变值对象, V1.0.11 ADR-0032）.

    Attributes:
        name: Pipeline 名称（默认 "default", V1.0.11 不开放自定义）
        pre_bridge: pre-bridge stages 的 StageDescriptor 元组
        post_bridge: post-bridge stages 的 StageDescriptor 元组
        has_router: 是否配置了 Router
        has_quota: 是否配置了 QuotaManager
        has_hooks: 是否实际配置了至少一个 Hook
        version: producer/API version (NOT schema_version; V1.1 deferred per ADR-0031)
    """

    # 必填: 结构
    pre_bridge: Tuple[StageDescriptor, ...]
    post_bridge: Tuple[StageDescriptor, ...]

    # 配置标志
    has_router: bool
    has_quota: bool
    has_hooks: bool

    # 可选
    name: str = "default"
    version: str = "1.0.11"


# ─────────────────────────────────────────────────────────────
# Module API
# ─────────────────────────────────────────────────────────────

__all__ = [
    "PipelineDescriptor",
]
