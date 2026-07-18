# AI Hub — CheckpointStage
# V1.0.3: Pipeline 可暂停/可恢复 (ADR-0023 ChatGPT 9.9/10 FINAL APPROVED)
#
# 验证 Pipeline 扩展性：第三个 Stage（Retry/Metrics/Checkpoint）。
#
# 关键设计原则 (ChatGPT 9.9/10 强烈建议):
#   ① Snapshot 是 Runtime Projection, 不是 ExecutionContext Serialization
#     - 主动挑选 Runtime 关键字段, 不是 pickle.dumps(ctx)
#   ② Checkpoint is a durability boundary, not an execution boundary
#     - Checkpoint 负责: 恢复
#     - Checkpoint 不负责: 控制执行
#   ③ Best Effort
#     - Execution 成功 → Checkpoint 写失败 → warning → Execution 仍 Success
#     - 不允许: Execution → Checkpoint Exception → Pipeline FAIL
#
# Contract 抽象 (ChatGPT Q2 关键采纳):
#   - 依赖 ExecutionStore Protocol (不绑定 SQLiteExecutionStore)
#   - 运行时仍传 SQLiteExecutionStore() 实例
#   - 遵循 Runtime Contract "Storage is Disposable" 原则
#   - 未来可换 Memory / Remote / S3 实现
#
# Stage 顺序 (默认):
#   [RetryStage, MetricsStage, CheckpointStage]
#   - Checkpoint 在最末, 捕获最终 bridge_result (含重试后)
#   - MetricsStage 注入的 server_metrics 被 Checkpoint 看到
#
# 关键不变量 (来自 Runtime Contract §9.1.4):
#   - MUST NOT 修改 ExecutionContext (仅写存储, 不改 ctx)
#   - MUST 写快照到 ExecutionStore (抽象)
#   - MUST NOT 抛异常 (写失败 → logger.warning → pass)
#   - MUST 仅快照 ctx 关键字段 (不存整个 ctx)
#   - MUST NOT serialize Runtime Object (Provider/Bridge/Router/ExecutionContext/Callable/File Handle)
#   - MUST 写 type="checkpoint" (与 EventBus 统一)
#   - SHOULD 在最末
#   - SHOULD be replayable (Snapshot 应能被未来 Resume 独立使用)
#
# 失败处理 (Best Effort):
#   - 写快照失败 → logger.warning → pass
#   - 构造快照失败 → logger.warning → pass
#   - 错误信息写入快照 error 字段 (供后续调试)
#
# API Stability: Experimental

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Optional

from core.bridge import BridgeResult
from core.provider import Provider
from core.task import Task
from planner.execution_event import ExecutionEvent
from planner.execution_store import ExecutionStore
from planner.pipeline import ExecutionContext

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# CheckpointSnapshot — Runtime Projection
# ─────────────────────────────────────────────────────────────

@dataclass
class CheckpointSnapshot:
    """Checkpoint 快照（V1.0.3）：Runtime Projection of ExecutionContext.

    设计原则 (ChatGPT 9.9/10 Q4):
      - **Snapshot 是 Runtime Projection, 不是 ExecutionContext Serialization**
      - 主动挑选 Runtime 关键字段 (str/int/float/bool/list/dict)
      - 禁止序列化 Runtime Object (Provider/Bridge/Router/ExecutionContext/Callable/File Handle)

    ChatGPT 9.9/10 Q5 JSON 强制:
      - to_dict() 返回 dict, 可被 json.dumps/json.loads 完整 round-trip

    关键字段:
      - task_id: 主键 (用于按 task_id 查询快照历史)
      - stage: "checkpoint" (固定标识)
      - timestamp: epoch seconds
      - task_content / task_capabilities: Task 关键字段
      - provider_name / bridge_name: Routing 决策 (name only, 不存对象)
      - bridge_result_*: BridgeResult 关键字段 (success/output/error/duration_ms/artifacts)
      - server_metrics: 提取自 Result.metadata (MetricsStage 注入)
      - error: 自身写快照时的错误 (Best Effort 错误捕获)
    """

    task_id: str
    stage: str
    timestamp: float
    task_content: str
    task_capabilities: list
    provider_name: str
    bridge_name: str
    bridge_result_success: bool
    bridge_result_output: str
    bridge_result_error: Optional[str]
    bridge_result_duration_ms: int
    bridge_result_artifacts: list
    server_metrics: dict
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """序列化为 dict (JSON 友好)."""
        return asdict(self)

    @classmethod
    def from_context(
        cls,
        ctx: ExecutionContext,
        timestamp: Optional[float] = None,
        error: Optional[str] = None,
    ) -> "CheckpointSnapshot":
        """从 ExecutionContext 构造快照 (Runtime Projection).

        关键约束 (ChatGPT 9.9/10 Q4):
          - 仅提取关键字段 (不 pickle 整个 ctx)
          - bridge_name 仅存类名 (不存对象)
          - server_metrics 仅 dict 类型 (MetricsStage 注入)

        Args:
            ctx: ExecutionContext (必须有 task + bridge_result)
            timestamp: epoch seconds (None 时用 time.time())
            error: 自身写快照时的错误 (默认 None)

        Returns:
            CheckpointSnapshot 实例
        """
        task = ctx.task
        br = ctx.bridge_result
        provider = ctx.provider
        bridge = ctx.bridge

        # 提取 server_metrics (从 result 优先, 否则空 dict)
        server_metrics: dict = {}
        if ctx.result is not None and isinstance(ctx.result.metadata, dict):
            raw_metrics = ctx.result.metadata.get("server_metrics", {})
            if isinstance(raw_metrics, dict):
                server_metrics = raw_metrics

        return cls(
            task_id=task.task_id,
            stage="checkpoint",
            timestamp=timestamp if timestamp is not None else time.time(),
            task_content=task.content,
            task_capabilities=list(task.capabilities),
            provider_name=provider.name if provider else "<unknown>",
            bridge_name=bridge.__class__.__name__ if bridge else "<unknown>",
            bridge_result_success=br.success,
            bridge_result_output=br.output,
            bridge_result_error=br.error,
            bridge_result_duration_ms=br.duration_ms,
            bridge_result_artifacts=list(br.artifacts),
            server_metrics=server_metrics,
            error=error,
        )


# ─────────────────────────────────────────────────────────────
# CheckpointStage — Runtime Stage
# ─────────────────────────────────────────────────────────────

class CheckpointStage:
    """Post-bridge Stage: 写 ExecutionContext Snapshot 到 ExecutionStore.

    关键不变量 (Runtime Contract §9.1.4):
      - 0 修改 ExecutionContext (仅写存储, pass)
      - 写失败 MUST NOT 抛异常 (Best Effort)
      - 依赖 ExecutionStore 抽象 (不绑定 SQLite)

    Stage 顺序 (默认):
      [RetryStage, MetricsStage, CheckpointStage]
      - 在最末, 捕获最终 bridge_result
      - server_metrics 从 ctx.result 提取 (MetricsStage 注入)

    API Stability: Experimental
    """

    def __init__(self, store: ExecutionStore):
        """构造 CheckpointStage.

        Args:
            store: ExecutionStore Protocol 实现
                   (默认: SQLiteExecutionStore, 也可 Memory/Remote/S3)

        Raises:
            ValueError: store 为 None
        """
        if store is None:
            raise ValueError(
                "CheckpointStage requires a non-None ExecutionStore. "
                "Pass SQLiteExecutionStore() (or any ExecutionStore impl)."
            )
        self.store = store
        self._name = "checkpoint"

    @property
    def name(self) -> str:
        return self._name

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        """处理 ctx: 写快照, pass.

        短路条件 (直接 pass):
          - ctx.stop = True
          - ctx.task is None
          - ctx.bridge_result is None

        写失败处理 (Best Effort):
          - 构造快照失败 → logger.warning → pass
          - store.append 抛异常 → logger.warning → pass
          - 错误信息可写入 snapshot.error (供后续调试)

        Returns:
            原 ctx (Stage 不修改 ExecutionContext)
        """
        # 短路
        if ctx.stop or ctx.task is None or ctx.bridge_result is None:
            return ctx

        # 构造快照
        try:
            snapshot = CheckpointSnapshot.from_context(ctx)
        except Exception as e:
            logger.warning(
                "CheckpointStage snapshot construction failed for task %s: %s",
                ctx.task.task_id, e,
            )
            return ctx  # Best Effort: pass

        # 写 ExecutionEvent
        try:
            event = ExecutionEvent(
                event_id=uuid.uuid4().hex,
                type="checkpoint",  # ExecutionEvent.type 字段
                plan_id=ctx.task.task_id,  # 用 task_id 作为 plan_id
                step_id=None,
                provider=snapshot.provider_name,
                latency_ms=snapshot.bridge_result_duration_ms,
                data=snapshot.to_dict(),  # Snapshot as JSON-friendly dict
            )
            self.store.append(event)
            logger.debug(
                "CheckpointStage wrote snapshot for task %s (event_id=%s)",
                snapshot.task_id, event.event_id,
            )
        except Exception as e:
            # Best Effort: 写失败 → warning → pass
            logger.warning(
                "CheckpointStage append failed for task %s: %s",
                ctx.task.task_id, e,
            )

        return ctx
