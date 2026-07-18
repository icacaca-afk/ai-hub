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
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, Optional

from core.bridge import BridgeResult
from core.provider import Provider
from core.task import Task
from planner.execution_event import ExecutionEvent
from planner.execution_store import ExecutionStore
from planner.pipeline import ExecutionContext
from planner.stage_descriptor import StageDescriptor

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Snapshot 大小保护 (ChatGPT 9.95/10 Q8 采纳)
# ─────────────────────────────────────────────────────────────
# 默认 1MB / 字段, 超过则截断 + warning
# 理由: Checkpoint 是 durability boundary, 写大对象会拖慢 Pipeline
# 未来可由配置驱动 (V1.x 后期再说)
SNAPSHOT_FIELD_MAX_BYTES = 1 * 1024 * 1024  # 1MB


def _truncate_field(value: Any, field_name: str, max_bytes: int = SNAPSHOT_FIELD_MAX_BYTES) -> Any:
    """截断大对象, 防止 Checkpoint 单字段膨胀.

    行为 (ADR §9.1.4 大对象策略):
      - str: 按字节截断 + 标注
      - list/dict: JSON 序列化后按字节截断
      - 其他: 保留原样
    """
    import json
    if isinstance(value, str):
        encoded = value.encode("utf-8", errors="replace")
        if len(encoded) > max_bytes:
            logger.warning(
                "CheckpointSnapshot: truncating field %s (%d bytes → %d bytes)",
                field_name, len(encoded), max_bytes,
            )
            return encoded[:max_bytes].decode("utf-8", errors="replace") + f"...[truncated {len(encoded) - max_bytes} bytes]"
        return value
    if isinstance(value, (list, dict)):
        try:
            encoded = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
            if len(encoded) > max_bytes:
                logger.warning(
                    "CheckpointSnapshot: truncating field %s (%d bytes → %d bytes)",
                    field_name, len(encoded), max_bytes,
                )
                truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
                return json.loads(truncated + '""')  # 截断后可能 JSON 损坏, 退回 list
        except (TypeError, ValueError):
            pass
        return value
    return value


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
      - snapshot_version: Snapshot Schema 版本 (从 1 开始, 为 Resume/Migration 预留)
      - task_id: 主键 (用于按 task_id 查询快照历史)
      - stage: "checkpoint" (固定标识)
      - timestamp: epoch seconds
      - task_content / task_capabilities: Task 关键字段
      - provider_name / bridge_name: Routing 决策 (name only, 不存对象)
      - bridge_result_*: BridgeResult 关键字段 (success/output/error/duration_ms/artifacts)
      - server_metrics: 提取自 Result.metadata (MetricsStage 注入)
      - aborted: Pipeline 是否被终止 (V1.0.4 新增, ChatGPT 9.9/10 Q4 采纳)
      - stopped_by: 终止来源 (V1.0.4 新增, e.g. "condition", "condition:skip")
      - error: 自身写快照时的错误 (Best Effort 错误捕获)
    """

    # Snapshot Schema 版本 (ChatGPT 9.95/10 采纳: 为 Resume / Migration 预留)
    # ClassVar 避免被 dataclass 当成 instance field
    SNAPSHOT_VERSION: ClassVar[int] = 1

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
    snapshot_version: int = 1
    aborted: bool = False  # V1.0.4 新增: Pipeline 是否被终止
    stopped_by: Optional[str] = None  # V1.0.4 新增: 终止来源
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """序列化为 dict (JSON 友好)."""
        d = asdict(self)
        # 确保 snapshot_version 显式输出 (供 Resume 端判断)
        d["snapshot_version"] = self.snapshot_version
        return d

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
          - aborted/stopped_by 从 ctx.metadata["condition_eval"] 提取 (V1.0.4 新增)

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

        # 提取 aborted / stopped_by (V1.0.4 新增, ChatGPT 9.9/10 Q4 采纳)
        # V1.0.7: 强类型优先, dict 兜底
        # V1.0.8: 改用 ctx.runtime.resolve_stop_reason(ctx) (净减 ~14 行, 采纳 ChatGPT 9.88/10 Q3)
        # 封装 4 级优先级: runtime.stopped_by → runtime.condition_eval.stopped_by
        #                 → ctx.metadata["condition_eval"]["stopped_by"] → ctx.stop → "stop_flag"
        stopped_by: Optional[str] = ctx.runtime.resolve_stop_reason(ctx)
        aborted = stopped_by is not None

        # 提取 server_metrics (V1.0.7: 优先 ctx.runtime.server_metrics, 兜底 Result.metadata)
        # V1.0.8 保持: 用 get_metrics() 统一接口 (返回 copy, V1.0.8 仍未做 V1.0.9 resolve_metrics)
        server_metrics: dict = {}
        ctx_runtime = getattr(ctx, "runtime", None)
        if ctx_runtime is not None and ctx_runtime.get_metrics():
            server_metrics = ctx_runtime.get_metrics()
        elif ctx.result is not None and isinstance(ctx.result.metadata, dict):
            raw_metrics = ctx.result.metadata.get("server_metrics", {})
            if isinstance(raw_metrics, dict):
                server_metrics = raw_metrics

        return cls(
            task_id=task.task_id,
            stage="checkpoint",
            timestamp=timestamp if timestamp is not None else time.time(),
            task_content=_truncate_field(task.content, "task_content"),
            task_capabilities=list(task.capabilities),
            provider_name=provider.name if provider else "<unknown>",
            bridge_name=bridge.__class__.__name__ if bridge else "<unknown>",
            bridge_result_success=br.success,
            bridge_result_output=_truncate_field(br.output, "bridge_result_output"),
            bridge_result_error=br.error,
            bridge_result_duration_ms=br.duration_ms,
            bridge_result_artifacts=_truncate_field(list(br.artifacts), "bridge_result_artifacts"),
            server_metrics=server_metrics,
            snapshot_version=cls.SNAPSHOT_VERSION,
            aborted=aborted,
            stopped_by=stopped_by,
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

    # V1.0.6: 显式 StageDescriptor (ADR-0026 ChatGPT 9.94/10 Critical Q7)
    # 关键字段 always_run_after_stop=True (V1.0.4 ChatGPT 9.95/10 采纳: Checkpoint 总是写, 即使 abort)
    descriptor = StageDescriptor(
        name="checkpoint",
        version=1,
        role="checkpoint",
        capabilities=frozenset({"persists_state"}),
        idempotent=True,
        has_side_effects=True,         # 写 ExecutionStore
        always_run_after_stop=True,    # V1.0.4 关键: 即使 abort 仍写
        description="Persists execution snapshot to ExecutionStore",
        owner="ai-hub",
        experimental=False,
    )

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
          - ctx.task is None
          - ctx.bridge_result is None

        **不短路 ctx.stop** (V1.0.4 调整, ChatGPT 9.9/10 Q4 关键采纳):
          - 即使 ctx.stop=True 也要写 Checkpoint
          - 原因: Workflow 终止也是 Runtime 事实, 需要记录 status=aborted / stopped_by
          - CheckpointSnapshot.from_context() 从 ctx.metadata.condition_eval 提取 stopped_by

        写失败处理 (Best Effort):
          - 构造快照失败 → logger.warning → pass
          - store.append 抛异常 → logger.warning → pass
          - 错误信息可写入 snapshot.error (供后续调试)

        Returns:
            原 ctx (Stage 不修改 ExecutionContext)
        """
        # 短路: 仅 task / bridge_result 缺失时 pass
        # (V1.0.4 调整: 移除 ctx.stop 短路, 让 Checkpoint 总是记录)
        if ctx.task is None or ctx.bridge_result is None:
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
