# AI Hub — Pipeline Stages Subpackage
# V1.0.2: 可插拔 Stage 集合
#
# ADR-0022 V1.0.2: RetryStage（Pipeline 扩展性首次验证）
# 未来 Stages (V1.0.3+):
#   - CheckpointStage (ADR-0023)
#   - ConditionStage (ADR-0024)
#
# 设计原则（来自 Runtime Contract §9.1）:
#   - Stage MUST NOT 修改 ExecutionEvent
#   - Stage MUST NOT 接触 SQLite/EventBus（除非显式订阅）
#   - Stage MUST 通过 ctx.with_xxx() 返回新 ExecutionContext
#   - Stage MUST 通过 ctx.stop = True 短路
#   - Stage SHOULD 保持 Side-Effect Minimal
#   - Stage 失败 MUST 返回有效 ctx（不抛异常）
#
# API Stability: Experimental

from planner.stages.retry_stage import (
    RetryStage,
    _default_retryable,
    compute_backoff_delay,
    SAFE_RETRY_ERROR_PATTERNS,
)

__all__ = [
    "RetryStage",
    "_default_retryable",
    "compute_backoff_delay",
    "SAFE_RETRY_ERROR_PATTERNS",
]
