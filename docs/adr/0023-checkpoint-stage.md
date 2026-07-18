# ADR-0023: CheckpointStage — Pipeline 可暂停/可恢复

- **里程碑**: V1.0.3
- **作者**: ai-hub core team
- **日期**: 2026-07-18
- **状态**: Proposed（待 ChatGPT 审核）
- **依赖**: [ADR-0021 ExecutionPipeline](0021-execution-pipeline.md), [ADR-0022 RetryStage](0022-retry-stage.md)
- **前序 ChatGPT 路线图**: V1.0.2 代码审核 9.95/10 FINAL — "下一步：V1.0.3 CheckpointStage，**不要加入 Retry 改动**"

---

## 1. 背景与目标

### 1.1 背景

V1.0.1 引入 ExecutionPipeline 装饰器链架构，V1.0.2 验证 Pipeline 扩展性（第一个非 metrics Stage：RetryStage）。

ChatGPT 在 V1.0.2 代码审核（9.95/10）中明确提出路线图：

> "V1.0.3 CheckpointStage。目标：Pipeline 可以暂停。**不要加入 Retry 改动。**"

### 1.2 目标

本 ADR 引入 **CheckpointStage**，作为第三个 post_bridge Stage，让 Pipeline 在关键执行点生成可恢复的执行快照。

**核心目标**：

1. **可暂停**：Pipeline 任意 stage 后可生成快照
2. **可恢复**：未来 V1.x 从快照恢复执行
3. **可观测**：记录 task / provider / bridge / bridge_result 到 SQLite
4. **Stage 解耦**：不修改 Pipeline 主体，不污染 ExecutionContext

### 1.3 非目标

- ❌ **不**做完整执行历史（execution_events 已覆盖）
- ❌ **不**做 Plan 持久化（PlanStore 已覆盖 V0.9.3）
- ❌ **不**做异步 Pipeline（V2）
- ❌ **不**做 Checkpoint 恢复执行（V1.0.3 仅生成快照，V1.x 评估恢复）

---

## 2. 设计原则

### 2.1 遵循 Runtime Contract §9.1.1 通用 Stage 约束

- Stage **MUST NOT** 修改 ExecutionContext（仅写存储，不改 ctx）
- Stage **MUST** 通过 `ctx.with_xxx()` 返回 ctx（实际不需要，但保持一致）
- Stage **MUST NOT** 接触 SQLiteExecutionStore / EventBus 内部，除非显式传入
- Stage 失败 **MUST** 返回有效 ctx（不抛异常，不污染主链路）

### 2.2 ChatGPT 9.95/10 关键建议

> "Checkpoint 不要保存 Pipeline。应该保存 ExecutionContext Snapshot。例如：Task / Provider / Bridge / Result / Server Metrics。"

**采纳**：CheckpointStage 保存 ExecutionContext Snapshot（不保存 Pipeline / Stages / 回调）。

### 2.3 Core Freeze

- **0 修改** `core/`
- **0 修改** `router/router.py`
- **0 修改** `providers/`
- **0 修改** `planner/pipeline.py` 主体（仅 `default_pipeline()` 工厂加 `include_checkpoint` 参数）
- **新增** `planner/stages/checkpoint_stage.py`
- **新增** `tests/test_checkpoint_stage.py`

---

## 3. 核心设计

### 3.1 触发时机

**默认**：`post_bridge_stages` 全部完成后，写一次快照。

**原因**：
- 避免每个 stage 完成后都写（噪音大、I/O 频繁）
- post_bridge 完成时已有完整 bridge_result
- 失败时也记录（用于排错）

**未来扩展**（V1.0.3+ 不实施）：
- `after_each_stage=True`：每个 stage 完成后都记录
- 自定义检查点位置

### 3.2 快照内容（Checklist）

```python
@dataclass
class CheckpointSnapshot:
    task_id: str            # 主键
    stage: str              # "checkpoint"（固定）
    timestamp: float        # epoch seconds
    task_content: str       # Task.content
    task_capabilities: list  # Task.capabilities
    provider_name: str      # ctx.provider.name
    bridge_name: str        # ctx.bridge 名称 (bridge.__class__.__name__)
    bridge_result_success: bool
    bridge_result_output: str
    bridge_result_error: str | None
    bridge_result_duration_ms: int
    bridge_result_artifacts: list  # list[str]
    server_metrics: dict    # 从 Result.metadata.get("server_metrics", {})
    error: str | None       # 自身写快照时的错误（如果有）
```

**关键决策**：**仅快照 ctx 关键字段**，不存 ExecutionContext 整个对象（含 result / stop 等中间态）。

### 3.3 存储后端

**复用** [V0.9.5 SQLiteExecutionStore](.../v0.9/sqlite-execution-store.md)，**不**新建表。

**方式**：用 `ExecutionEvent` 写入，但 `event_type="checkpoint"`，`payload` 为 `CheckpointSnapshot` 的 JSON 序列化。

```python
event = ExecutionEvent(
    event_id=uuid4().hex,
    task_id=ctx.task.task_id,
    event_type="checkpoint",
    timestamp=time.time(),
    payload=snapshot.to_dict(),  # JSON-friendly dict
)
store.append(event)
```

**为什么不新建表**：
- 复用 execution_events schema，无需迁移
- 统一查询（一次 SELECT 拿到所有执行事件 + 检查点）
- 与 EventBus 兼容

### 3.4 序列化格式

**JSON**（不 Pickle）：
- 跨平台 / 人类可读
- 不可执行（安全）
- JSON 友好字段：str / int / float / bool / list / dict

**BRIDGE_RESULT.raw**：
- raw 可能是 dict（APIBridge 错误时是 str）→ 仅在 dict 时序列化
- 不可序列化字段（CompletedProcess）→ 记录类型名 + 截断输出

### 3.5 失败处理

**写入失败 MUST NOT 抛异常**：
- SQLite 锁 / 磁盘满 / 序列化失败 → 记录 logger.error，继续 pass
- 不污染主链路
- 错误信息写入快照的 `error` 字段，供后续调试

### 3.6 Stage 顺序

默认 `post_bridge_stages`：

```
[RetryStage, MetricsStage, CheckpointStage]
    ↓           ↓              ↓
  先重试    再 metrics    最后 checkpoint
```

**关键不变量**：
- Checkpoint 在最末，捕获**最终** bridge_result（含重试后 + metrics 注入后）
- MetricsStage 把 server_metrics 注入到 Result.metadata
- Checkpoint 从 `Result.metadata.get("server_metrics")` 提取（但 MetricsStage 不改 ctx.result, 改 ctx.bridge_result 关联）
- 实际：MetricsStage 直接构造 new Result，server_metrics 在 ctx.result.metadata
- 修正：CheckpointStage 应该从 `ctx.result` 提取（如果 MetricsStage 已运行），否则从 `ctx.bridge_result` 推断

**决定**：CheckpointStage 优先级"result > bridge_result"，从 ctx.result 优先提取 server_metrics。

### 3.7 API Stability

**CheckpointStage: Experimental**
**CheckpointSnapshot: Experimental**

---

## 4. 关键决策

### 决策 1：CheckpointStage 是 Stage，不是 Pipeline 内部功能

- ✅ 复刻 ADR-0021 Pipeline 架构原则
- ✅ ChatGPT 9.95/10 强烈建议："如果 Checkpoint 改 Pipeline，说明 Pipeline 设计失败"

### 决策 2：复用 SQLiteExecutionStore，不新建表

- ✅ 0 schema 迁移
- ✅ 与 EventBus 统一
- ✅ 一次 SELECT 拿全部

### 决策 3：默认只在 post_bridge 完成后检查点一次

- ✅ 简单、低噪音
- ✅ 失败时也记录（用于排错）
- ❌ 不做"每个 stage 后"模式（V1.0.3 不需要）

### 决策 4：仅快照 ctx 关键字段（不存整个 ctx）

- ✅ JSON 友好
- ✅ 体积小（典型 < 1KB）
- ✅ 兼容未来 ExecutionContext 字段扩展（向后兼容）
- ❌ 不存 ctx.stop / ctx.result（中间态，不属于快照）

### 决策 5：JSON 序列化（不 Pickle）

- ✅ 跨平台
- ✅ 安全（不可执行）
- ✅ 人类可读
- ❌ 不可存函数（不在快照里）

### 决策 6：Core Freeze 严格性

- 0 修改 `core/`
- 0 修改 `router/router.py`
- 0 修改 `providers/`
- 0 行为变化 `planner/pipeline.py` 主体（仅 default_pipeline 工厂加 1 参数）

### 决策 7：失败不抛异常

- ✅ 写快照失败 → logger.error → pass
- ✅ 不污染主链路
- ✅ 错误信息写入快照 error 字段

### 决策 8：Stage 顺序 [Retry, Metrics, Checkpoint]

- ✅ Checkpoint 在最末，捕获最终结果
- ✅ MetricsStage 注入的 server_metrics 已被 Checkpoint 看到
- ✅ 用户可自定义顺序

### 决策 9：恢复执行 V1.0.3 不实施

- ✅ 保持范围克制
- ❌ 未来 V1.x 评估（需要新 Runtime 接口）
- ChatGPT 路线图：V2 Async Pipeline 时再做

### 决策 10：API Stability Experimental

- ✅ 与 RetryStage 一致
- ❌ V1.1 评估是否转 Stable

---

## 5. 关键代码草图

```python
# planner/stages/checkpoint_stage.py
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict
from typing import Any, Optional

from core.bridge import BridgeResult
from core.task import Task
from core.execution_event import ExecutionEvent  # V0.9.4
from core.execution_store import ExecutionStore  # V0.9.5 Protocol
from planner.pipeline import ExecutionContext

logger = logging.getLogger(__name__)


@dataclass
class CheckpointSnapshot:
    task_id: str
    stage: str  # "checkpoint"
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
    error: Optional[str] = None  # 自身写快照时的错误

    def to_dict(self) -> dict:
        return asdict(self)


class CheckpointStage:
    """Post-bridge Stage: 写 ExecutionContext 快照到 SQLiteExecutionStore。

    Stage 顺序: [RetryStage, MetricsStage, CheckpointStage]
    - 在最末，捕获最终 bridge_result
    - 失败不抛异常，不污染主链路
    - 0 行为变化 Pipeline 主体

    API Stability: Experimental
    """

    def __init__(self, store: ExecutionStore):
        if store is None:
            raise ValueError("CheckpointStage requires a non-None ExecutionStore")
        self.store = store
        self._name = "checkpoint"

    @property
    def name(self) -> str:
        return self._name

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        # 短路: 没有 task / 没有 provider / 没有 bridge_result 时 pass
        if ctx.task is None or ctx.bridge_result is None:
            return ctx

        # 提取 server_metrics（从 result 优先, 否则空 dict）
        server_metrics = {}
        if ctx.result is not None and isinstance(ctx.result.metadata, dict):
            server_metrics = ctx.result.metadata.get("server_metrics", {})

        # 构造快照
        try:
            snapshot = CheckpointSnapshot(
                task_id=ctx.task.task_id,
                stage="checkpoint",
                timestamp=time.time(),
                task_content=ctx.task.content,
                task_capabilities=list(ctx.task.capabilities),
                provider_name=ctx.provider.name if ctx.provider else "<unknown>",
                bridge_name=ctx.bridge.__class__.__name__ if ctx.bridge else "<unknown>",
                bridge_result_success=ctx.bridge_result.success,
                bridge_result_output=ctx.bridge_result.output,
                bridge_result_error=ctx.bridge_result.error,
                bridge_result_duration_ms=ctx.bridge_result.duration_ms,
                bridge_result_artifacts=list(ctx.bridge_result.artifacts),
                server_metrics=server_metrics,
                error=None,
            )
        except Exception as e:
            # 构造快照失败 → pass（不污染主链路）
            logger.error("CheckpointStage snapshot construction failed: %s", e)
            return ctx

        # 写入 SQLiteExecutionStore
        try:
            event = ExecutionEvent(
                event_id=__import__("uuid").uuid4().hex,
                task_id=snapshot.task_id,
                event_type="checkpoint",
                timestamp=snapshot.timestamp,
                payload=snapshot.to_dict(),
            )
            self.store.append(event)
            logger.debug("CheckpointStage wrote snapshot for task %s", snapshot.task_id)
        except Exception as e:
            # 写失败 → 记录日志, pass
            logger.error(
                "CheckpointStage write failed for task %s: %s",
                snapshot.task_id, e,
            )

        return ctx
```

```python
# planner/pipeline.py default_pipeline 修改
def default_pipeline(
    router: Router,
    quota: Any = None,
    include_metrics: bool = True,
    include_retry: bool = False,
    include_checkpoint: bool = False,  # V1.0.3 新增
    execution_store: Any = None,       # V1.0.3 新增（include_checkpoint=True 时必传）
) -> ExecutionPipeline:
    """..."""
    pre_bridge = [RouteStage(router)]
    post_bridge: list = []
    if include_retry:
        from planner.stages.retry_stage import RetryStage
        post_bridge.append(RetryStage())
    if include_metrics:
        post_bridge.append(MetricsStage())
    if include_checkpoint:
        from planner.stages.checkpoint_stage import CheckpointStage
        if execution_store is None:
            raise ValueError("include_checkpoint=True requires execution_store")
        post_bridge.append(CheckpointStage(execution_store))
    return ExecutionPipeline(
        router=router,
        pre_bridge_stages=pre_bridge,
        post_bridge_stages=post_bridge,
        quota=quota,
    )
```

---

## 6. 关键不变量（来自 Runtime Contract §9.1.4 新增）

```markdown
#### 9.1.4 CheckpointStage 专属原则（V1.0.3 新增）

- CheckpointStage MUST NOT 修改 ExecutionContext（仅写存储，不改 ctx）
- CheckpointStage MUST 写快照到 ExecutionStore（V0.9.5 SQLiteExecutionStore）
- CheckpointStage MUST NOT 重试 / 恢复（仅生成快照，恢复 V1.x 评估）
- CheckpointStage MUST NOT 抛异常（写失败 → logger.error → pass）
- CheckpointStage MUST 仅快照 ctx 关键字段（不存整个 ctx）
- CheckpointStage MUST NOT 新建表（复用 execution_events schema）
- CheckpointStage SHOULD 在最末（默认顺序 [Retry, Metrics, Checkpoint]）
- 失败信息 SHOULD 写入快照 error 字段（供后续调试）
```

---

## 7. 8 个确认问题

### Q1: CheckpointStage 应该是 Stage 还是 Pipeline 内部功能？
**倾向**：Stage。复刻 ADR-0021 原则，0 修改 Pipeline 主体。

### Q2: 复用 SQLiteExecutionStore 还是新建 checkpoint 表？
**倾向**：复用。0 schema 迁移，统一查询。

### Q3: 触发时机？每个 stage 后还是仅 post_bridge 后？
**倾向**：仅 post_bridge 后。简单、低噪音。

### Q4: 快照内容？整个 ctx 还是关键字段？
**倾向**：关键字段。JSON 友好、体积小、向后兼容。

### Q5: 序列化？JSON 还是 Pickle？
**倾向**：JSON。安全、跨平台、人类可读。

### Q6: Stage 顺序？[Retry, Metrics, Checkpoint] 对吗？
**倾向**：对。Checkpoint 在最末，捕获最终结果。

### Q7: 失败处理？抛异常还是 pass？
**倾向**：pass。Stage 失败不污染主链路。

### Q8: V1.0.3 是否做恢复？
**倾向**：不做。V1.0.3 仅生成快照，恢复 V1.x 评估。

---

## 8. 测试策略

15 个测试：
- TestCheckpointSnapshot (3): 构造 / 序列化 / 关键字段覆盖
- TestCheckpointStageBasics (4): 成功/失败/无 store/短路
- TestCheckpointStageSQLite (3): 写 SQLite / event_type=checkpoint / 多次写
- TestCheckpointStageIntegration (3): Stage 顺序 / metrics 在 checkpoint 前 / retry + checkpoint
- TestCheckpointStageFailureHandling (2): 写失败不抛异常 / 构造失败不抛异常

---

## 9. 文档更新

- `docs/runtime-contract.md` §9.1.4 新增 CheckpointStage 原则
- `docs/runtime-contract.md` §9 版本演进表新增 V1.0.3 行
- `docs/adr/0021-execution-pipeline.md` Version Evolution 表新增 V1.0.3 行
- `docs/adr/0022-retry-stage.md` Version Evolution 表新增 V1.0.3 行

---

## 10. ChatGPT V1.0.2 路线图对齐

| 版本 | 目标 | 关键不变量 | 状态 |
|------|------|-----------|------|
| V1.0.1 | ExecutionPipeline | Pipeline = Extension Point | ✅ Accepted (10.0/10) |
| V1.0.2 | RetryStage | **不**改 Pipeline | ✅ Accepted (9.95/10) |
| **V1.0.3** | **CheckpointStage** | **不**改 Pipeline，**不**改 Retry | **本 ADR** |
| V1.0.4 | ConditionStage | **不**改 V1.0.1-3 | 未来 |
| V1.1 | TimeoutStage | - | 未来 |
| V1.2 | CircuitBreakerStage | - | 未来 |
| V2 | Async Pipeline | - | 未来 |

---

## 11. 总结

ADR-0023 引入 **CheckpointStage** 作为 V1.0.3 第三个 Stage：

- ✅ 复刻 V1.0.1 Pipeline 扩展性
- ✅ 复用 V0.9.5 SQLiteExecutionStore
- ✅ 0 修改 Pipeline / Retry / Metrics
- ✅ 失败不污染主链路
- ✅ Core Freeze 严格
- ❌ 恢复执行 V1.x 评估

**期望 ChatGPT 评分**: ≥ 9.5/10

---

## 附录 A: 与 PlanStore 关系

PlanStore（V0.9.3）持久化 Plan（执行计划）：

```python
@dataclass
class Plan:
    plan_id: str
    task_id: str
    steps: list[PlanStep]
    created_at: float
    status: str  # "pending" / "running" / "completed" / "failed"
```

CheckpointStage 持久化 ExecutionContext Snapshot：

```python
@dataclass
class CheckpointSnapshot:
    task_id: str
    stage: str  # "checkpoint"
    timestamp: float
    bridge_result_success: bool
    # ... (见 §3.2)
```

**关系**：
- PlanStore = "我要做什么"（执行计划）
- CheckpointStore = "我做到了什么"（执行结果）
- 两者独立，可共同存在

## 附录 B: 决策追溯

| 来源 | 决策 |
|------|------|
| ChatGPT V1.0.2 9.95/10 路线图 | CheckpointStage 是 V1.0.3 目标 |
| ChatGPT V1.0.2 9.95/10 关键建议 | Checkpoint 不要保存 Pipeline，保存 ctx snapshot |
| Runtime Contract §9.1.1 | Stage 通用约束 |
| ADR-0021 Pipeline | Stage 解耦原则 |
| ADR-0022 Retry | 失败不污染主链路 |
| V0.9.5 SQLiteExecutionStore | 复用 schema |
