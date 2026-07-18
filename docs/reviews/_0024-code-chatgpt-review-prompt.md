# ChatGPT 代码层审核 prompt — ADR-0024 V1.0.4 ConditionStage 实施

## 背景

ai-hub 项目 V1.0.4 ConditionStage 实施已完成，请审核代码设计。

- **ADR**: [0024-condition-stage.md](https://...) (V1.0.4 Accepted 9.9/10)
- **实施 commit**: d8f959d "feat: V1.0.4 ConditionStage 实施"
- **测试基线**: 350 passed 关键测试, 0 failed
- **依赖**: ADR-0021 ExecutionPipeline / ADR-0022 RetryStage / ADR-0023 CheckpointStage (均已 Accepted)
- **目标**: 让 Pipeline 真正成为 Workflow Runtime — 条件分支 / 跳过 / 终止

## 实施范围（5 个文件，1459 行新增）

### 新增
- `planner/stages/condition_stage.py` (~200 行) — ConditionStage + ConditionEval + Condition
- `tests/test_condition_stage.py` (~470 行) — 30 tests, 7 类

### 修改
- `planner/pipeline.py` `default_pipeline()` 工厂 + `Pipeline.run()` 增量
- `planner/executor.py` `PlanExecutor` 透传
- `planner/stages/__init__.py` 导出 ConditionStage + ConditionEval + Condition
- `tests/test_checkpoint_stage.py` 4 个 V1.0.4 aborted/stopped_by 边界测试
- `planner/stages/checkpoint_stage.py` aborted/stopped_by 字段 + 从 metadata 提取

## 关键设计

### 1. Stage 职责定位（关键约束）

**Condition is a control boundary, not a data boundary.**

```python
# MUST NOT: 修改 ctx.task / ctx.bridge_result / ctx.provider
# MUST: 仅在 condition 触发 skip/abort 时设置 ctx.stop = True
# MUST: 求值结果写入 ctx.metadata["condition_eval"]
```

### 2. Condition 抽象（关键设计）

**Condition is a callable, not a DSL.**

```python
from typing import Callable
from planner.pipeline import ExecutionContext

Condition = Callable[[ExecutionContext], bool]
```

- V1.0.4 仅 `callable(ctx) -> bool`
- **不**做 DSL 表达式
- **不**做 JSON Schema 条件
- 用户写 `lambda ctx: ctx.bridge_result.success`

### 3. 三个动作（关键语义）

```python
VALID_ACTIONS = ("continue", "skip", "abort")
```

- `continue` — 继续执行后续 Stage
- `skip` — 跳过后续 Stage（视为 Workflow 正常结束）
- `abort` — 主动终止 Workflow（紧急停止）

**skip vs abort 关键区别**（ChatGPT 9.9/10 Q3 采纳）：
- 两者都设 `ctx.stop = True`
- 区别在 `ctx.metadata["condition_eval"]["stopped_by"]`:
  - skip: `"condition:NAME:skip"` (正常结束)
  - abort: `"condition:NAME:abort"` (主动终止)

### 4. Stage 顺序

`[RetryStage, MetricsStage, ConditionStage, CheckpointStage]`

- Condition 在 Checkpoint 前: Condition 先写 metadata
- Condition 在 Metrics 后: 终止决策基于最终结果

### 5. Fail-Closed（关键安全）

```python
try:
    result = bool(self.condition(ctx))
except Exception as e:
    logger.warning(...)
    result = False  # 异常视为条件不满足
```

- Condition 异常 → fail-closed (视为 False)
- Stage 自身异常 → return ctx (Best Effort)
- 与 Checkpoint / Retry 的 Best Effort 一致

### 6. Deterministic（关键约束）

Runtime Contract §9.1.5:
- **`condition` MUST be deterministic for the same ExecutionContext**
- 不应使用 random() / time() / network() / sleep()
- 否则 Checkpoint Replay 可能不一致

### 7. 审计写入 ctx.metadata

```python
ctx.metadata["condition_eval"] = {
    "stage": "condition",
    "condition_name": self._name,  # V1.0.4 关键 (ChatGPT 9.9/10 Q6 采纳)
    "result": bool(result),
    "action": action,
    "timestamp": time.time(),
    "stopped_by": stopped_by,  # None or "condition:NAME:skip/abort"
}
```

### 8. Pipeline.run() 关键增量（V1.0.4 ChatGPT 9.9/10 Q4 采纳）

**问题**：V1.0.3 Pipeline.run() 在 ctx.stop=True 时立即 return，导致 CheckpointStage 不执行。
**解决**：V1.0.4 Pipeline.run() 让 CheckpointStage 在 abort 后仍执行（Runtime Observability）。

```python
# 3. Post-bridge stages
aborted_idx = -1
for i, stage in enumerate(self.post_bridge_stages):
    ctx = stage(ctx)
    if ctx.stop:
        aborted_idx = i
        break

# 4. V1.0.4 关键: 如果 stop, 仍执行剩余 CheckpointStage
if ctx.stop and aborted_idx >= 0:
    for stage in self.post_bridge_stages[aborted_idx + 1:]:
        if stage.name == "checkpoint" and hasattr(stage, "store"):
            ctx = stage(ctx)  # 记录 abort 事实
    # 然后 return
    ...
```

### 9. CheckpointStage aborted/stopped_by 字段（V1.0.4 增量）

```python
@dataclass
class CheckpointSnapshot:
    ...
    aborted: bool = False
    stopped_by: Optional[str] = None
```

- `from_context()` 从 `ctx.metadata["condition_eval"]["stopped_by"]` 提取
- 兜底: `ctx.stop=True` → `stopped_by="stop_flag"`
- 移除 V1.0.3 的 `ctx.stop` 短路（仅短路 `task=None` / `bridge_result=None`）

### 10. Core Freeze

- **0 修改** `core/`
- **0 修改** `router/router.py`
- **0 修改** `providers/`
- **修改** `planner/pipeline.py` (Pipeline.run() abort-after-checkpoint 增量 + default_pipeline 加 5 参数)
- **修改** `planner/executor.py` (PlanExecutor 透传 5 参数)
- **新增** `planner/stages/condition_stage.py`
- **新增** `tests/test_condition_stage.py`

## 测试覆盖

### ConditionStage (30 tests, 7 类)

- TestConditionEval (3): 构造 / to_dict / stopped_by 可空
- TestConditionStageBasics (5): 校验 / 默认 / 自定义 name
- TestConditionStageShortCircuit (3): task=None / bridge_result=None / 不短路 stop
- TestConditionStageActions (6): 3 动作 × 2 condition
- TestConditionStageFailureHandling (3): 异常 fail-closed / bool 强制转换
- TestConditionStageChatGPTEdgeCases (5): condition_name / metadata 覆盖 / 不修改 task / 不修改 br / 调用一次
- TestConditionStagePipelineIntegration (5): pipeline abort 写 Checkpoint / pipeline skip 写 Checkpoint / Retry+Condition

### CheckpointStage V1.0.4 增量 (4 tests)

- test_aborted_field_written_from_condition_eval
- test_aborted_false_when_no_condition_eval
- test_checkpoint_written_even_when_ctx_stop
- test_stopped_by_fallback_to_stop_flag

## 关键约束 (Runtime Contract §9.1.5)

**ConditionStage MUST**:
- 接受 `Callable[[ExecutionContext], bool]` 作为条件
- 在 condition 为 True 时按 on_true 决定动作
- 在 condition 为 False 时按 on_false 决定动作
- 在 action="skip" 或 "abort" 时设置 `ctx.stop = True`
- 在 condition 抛异常时视为 False (fail-closed)
- 在 Stage 自身抛异常时返回原 ctx (Best Effort)
- 将求值结果写入 `ctx.metadata["condition_eval"]`
- **`condition` MUST be deterministic for the same ExecutionContext**

**ConditionStage MUST NOT**:
- 修改 ctx.task / ctx.bridge_result / ctx.provider
- 接触 SQLiteExecutionStore / EventBus 内部
- 抛异常
- 引入新的 ctx 字段

## 审核问题

**Q1 架构**: Condition 作为第四个 Stage 是否正确？Stage 顺序 [Retry, Metrics, Condition, Checkpoint] 是否最优？

**Q2 Condition 抽象**: `Callable[[ExecutionContext], bool]` 是否够用？是否需要支持 async callable / 装饰器？

**Q3 三个动作**: continue/skip/abort 语义是否清晰？stopped_by 命名 `"condition:NAME:skip/abort"` 是否合理？

**Q4 Pipeline.run() 关键增量**: abort 后仍执行 CheckpointStage 是否正确？是否影响其他 Stage 顺序场景？

**Q5 Fail-Closed**: condition 异常视为 False 是否合理？是否需要 fail-open 选项？

**Q6 ctx.metadata 审计**: condition_eval 结构是否合理？condition_name 字段是否够用？

**Q7 CheckpointStage aborted/stopped_by**: 字段定义是否合理？stopped_by 兜底 "stop_flag" 是否合理？

**Q8 Core Freeze**: 修改 Pipeline.run() 是否破坏"Pipeline 主体 0 行为变化"原则？0 修改 core/router/providers 是否合理？

**Q9 测试覆盖**: 30+4 = 34 tests (V1.0.4 新增) 是否足够？是否需要 Pipeline E2E 测试？

**Q10 Runtime Contract §9.1.5**: 7 MUST + 4 MUST NOT + 1 deterministic MUST 是否完整？

**Q11 整体评分**: 9.5+/10 评分依据。

## 期望

- 综合评分 ≥ 9.5/10
- 阻塞性调整: 0-1 项
- 非阻塞性建议: 任意
- 明确 APPROVED / NEEDS REVISION

## 风格指南

按 V1.0.2 (9.9/10) / V1.0.3 (9.9/10 ADR / 9.95/10 代码) 标准：
- 直接给评分 + 分项
- 引用具体 ADR 节号 + 代码行
- 拒绝方案时说明"为什么 X 比 Y 好"
- 路线图强建议
