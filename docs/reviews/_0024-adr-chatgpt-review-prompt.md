# ChatGPT ADR 审核 prompt — ADR-0024 V1.0.4 ConditionStage 草案

## 背景

ai-hub 项目 V1.0.4 ConditionStage 草案已写好，请审核 ADR 设计。

- **ADR**: [0024-condition-stage.md](https://...) (Proposed, 待审)
- **前序 ChatGPT 路线图**: V1.0.3 代码审核 9.95/10 — "**V1.0.4 ConditionStage**, 提供 Workflow Control"
- **依赖**: ADR-0021 ExecutionPipeline / ADR-0022 RetryStage / ADR-0023 CheckpointStage (均已 Accepted)
- **目标**: 让 Pipeline 真正成为 Workflow Runtime — 条件分支 / 跳过 / 终止

## 关键设计

### 1. Stage 职责定位 (ChatGPT 9.95/10 路线图强烈建议)

**Condition is a control boundary, not a data boundary.**
- 负责：控制（continue/skip/abort）
- 不负责：数据（不修改 ctx.task / ctx.bridge_result）
- 与 Checkpoint（持久化）/ Retry（重试）完全分离

### 2. Condition 抽象 (ChatGPT 9.95/10 §2.5 关键)

**Condition is a callable, not a DSL.**

```python
from typing import Callable
from planner.pipeline import ExecutionContext

Condition = Callable[[ExecutionContext], bool]
```

- V1.0.4 仅 `callable(ctx) -> bool`
- **不**做 DSL 表达式（`bridge_result.success == True`）
- **不**做 JSON Schema 条件
- 用户写 `lambda ctx: ctx.bridge_result.success`
- 未来 V1.1+ 可扩展 DSL

### 3. 三个动作

```python
on_true: Literal["continue", "skip", "abort"] = "continue"
on_false: Literal["continue", "skip", "abort"] = "continue"
```

- `continue` — 继续执行后续 Stage
- `skip` — 跳过后续 Stage（设置 `ctx.stop = True`）
- `abort` — 终止 Pipeline（设置 `ctx.stop = True`）

### 4. Stage 顺序

`[RetryStage, MetricsStage, ConditionStage, CheckpointStage]`

- Condition 在 Checkpoint 前: 终止的 Pipeline 不写 Checkpoint
- Condition 在 Metrics 后: 终止决策基于最终结果
- (对比: V1.0.3 Checkpoint 顺序是 `..., CheckpointStage`)

### 5. Fail-Closed (ChatGPT §2.6 关键)

```python
try:
    result = self.condition(ctx)
except Exception as e:
    logger.warning(...)
    result = False  # 异常视为条件不满足
```

- 单一 Condition 失败不阻塞 Pipeline
- 与 Checkpoint / Retry 的 Best Effort 一致

### 6. 审计写入 ctx.metadata

```python
ctx.metadata["condition_eval"] = {
    "stage": "condition",
    "result": bool(result),
    "action": action,
    "timestamp": time.time(),
}
```

- 不引入新 ctx 字段
- 复用 Metadata 机制 (Runtime Contract §5.2)
- 供后续 Stage (特别是 Checkpoint) 看到

### 7. Core Freeze

- **0 修改** `core/`
- **0 修改** `router/router.py`
- **0 修改** `providers/`
- **0 修改** `planner/pipeline.py` 主体（仅 `default_pipeline()` 工厂加 3 参数）
- **新增** `planner/stages/condition_stage.py`
- **新增** `tests/test_condition_stage.py`

## 关键约束 (Runtime Contract §9.1.5 新增)

**ConditionStage MUST**:
- 接受 `Callable[[ExecutionContext], bool]` 作为条件
- 在 condition 为 True 时按 on_true 决定动作
- 在 condition 为 False 时按 on_false 决定动作
- 在 action="skip" 或 "abort" 时设置 `ctx.stop = True`
- 在 condition 抛异常时视为 False (fail-closed)
- 在 Stage 自身抛异常时返回原 ctx (Best Effort)
- 将求值结果写入 `ctx.metadata["condition_eval"]`

**ConditionStage MUST NOT**:
- 修改 ctx.task / ctx.bridge_result / ctx.provider
- 接触 SQLiteExecutionStore / EventBus 内部 (除非显式传入)
- 抛异常
- 引入新的 ctx 字段

## 关键决策

| # | 决策 | 理由 |
|---|------|------|
| #1 | Stage 顺序: Condition 在 Checkpoint 前 | 终止的 Pipeline 不写 Checkpoint |
| #2 | 单 Condition 而非链 | V1.0.4 优先证明概念, V1.1 评估链 |
| #3 | fail-closed (异常视为 False) | Best Effort 一致 |
| #4 | 审计写入 ctx.metadata | 不引入新 ctx 字段, 复用 Metadata |
| #5 | 0 修改 Pipeline 主体 | 与 V1.0.1/2/3 一致 |

## 未来扩展 (V1.1+)

- V1.1 Condition 链（`conditions: list[Condition]`）
- V1.1 DSL 表达式（基于 Lark 等）
- V1.1 Condition 模板（`on_success()` / `on_failure()` / `on_metric()`）

## 关键确认问题

1. **API 命名**：`ConditionStage` / `condition_eval` / `on_true` / `on_false` 是否清晰？
2. **Stage 顺序**：Condition 在 Checkpoint 前是否合理？
3. **fail-closed**：异常视为 False 是否合理？是否需要 fail-open 选项？
4. **审计机制**：`ctx.metadata["condition_eval"]` 是否够用？
5. **DSL 推迟**：V1.0.4 不做 DSL 是否可接受？
6. **Condition 链推迟**：V1.0.4 不做链是否可接受？
7. **默认值**：`on_true="continue"`, `on_false="continue"` 是否合理？
8. **测试覆盖**：15 单元 + 5 集成 + 6 边界 = 26 tests，是否够？

## 审核问题

请按以下维度审核：

**Q1 架构**: Condition 作为第四个 Stage 是否正确？是否与 Retry/Metrics/Checkpoint 互补？

**Q2 抽象**: `Callable[[ExecutionContext], bool]` 作为 Condition 接口是否合理？是否应该支持 async callable / 装饰器？

**Q3 三个动作 (continue/skip/abort)**: 是否清晰？是否需要增加 `retry` 动作（让 Condition 触发重试）？

**Q4 Stage 顺序**: Condition 在 Checkpoint 前是否合理？是否应该让 Checkpoint 总能记录 Condition 决策？

**Q5 fail-closed**: 异常视为 False 是否合理？是否需要 fail-open / fail-default（可配置）？

**Q6 ctx.metadata 审计**: 是否够用？是否应该新增独立 ctx.condition_eval？

**Q7 Core Freeze**: 0 修改 core/router/providers 是否合理？是否应该让 Condition 显式接触 EventBus？

**Q8 测试覆盖**: 26 tests (15 单元 + 5 集成 + 6 边界) 是否足够？是否需要 E2E 测试？

**Q9 未来扩展**: V1.0.4 不做 DSL / 链 / 模板是否合理？是否会限制用户场景？

**Q10 Runtime Contract §9.1.5**: 7 MUST + 4 MUST NOT 是否完整？是否需要补充"Condition 是幂等的"约束？

**Q11 关键不变量**: "Condition is a control boundary, not a data boundary" 是否应该明确写入 ADR 标题？

**Q12 整体评分**: 9.5+/10 评分依据。

## 期望

- 综合评分 ≥ 9.5/10
- 阻塞性调整: 0-1 项
- 非阻塞性建议: 任意
- 明确 APPROVED / NEEDS REVISION

## 风格指南

按 V1.0.2 (9.9/10) / V1.0.3 (9.9/10 ADR / 9.95/10 代码) 标准：
- 直接给评分 + 分项
- 引用具体 ADR 节号
- 拒绝方案时说明"为什么 X 比 Y 好"
- 路线图强建议
