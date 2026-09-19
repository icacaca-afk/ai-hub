# AI Hub — Pipeline Stages Subpackage
# V1.0.2: 可插拔 Stage 集合
#
# V1.0.2: RetryStage (ADR-0022)
# V1.0.3: CheckpointStage (ADR-0023)
# V1.0.4: ConditionStage (ADR-0024)
# 未来 Stages (V1.1+):
#   - TimeoutStage (V1.1)
#   - CircuitBreakerStage (V1.2)
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
from planner.stages.checkpoint_stage import (
    CheckpointStage,
    CheckpointSnapshot,
)
from planner.stages.condition_stage import (
    ConditionStage,
    ConditionEval,
    Condition,
    VALID_ACTIONS,
)
from planner.predicate_descriptor import PredicateDescriptor

__all__ = [
    # V1.0.2: RetryStage
    "RetryStage",
    "_default_retryable",
    "compute_backoff_delay",
    "SAFE_RETRY_ERROR_PATTERNS",
    # V1.0.3: CheckpointStage
    "CheckpointStage",
    "CheckpointSnapshot",
    # V1.0.4: ConditionStage
    "ConditionStage",
    "ConditionEval",
    "Condition",
    "VALID_ACTIONS",
    # V1.0.12: explicit predicate semantics
    "PredicateDescriptor",
]
