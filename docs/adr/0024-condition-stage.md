# ADR-0024: ConditionStage — Pipeline Workflow Control (Control Boundary)

- **里程碑**: V1.0.4
- **作者**: ai-hub core team
- **日期**: 2026-07-18
- **状态**: Accepted（[ChatGPT 9.9/10 FINAL APPROVED](../reviews/0024-adr-chatgpt-review.md)）
- **依赖**: [ADR-0021 ExecutionPipeline](0021-execution-pipeline.md), [ADR-0022 RetryStage](0022-retry-stage.md), [ADR-0023 CheckpointStage](0023-checkpoint-stage.md)
- **前序 ChatGPT 路线图**: V1.0.3 代码审核 9.95/10 FINAL — "**V1.0.4 ConditionStage**, 提供 Workflow Control. 不要再扩展 Retry 或 Checkpoint"

> **Condition is a control boundary, not a data boundary.**
> Condition 是控制边界，不是数据边界。

---

## 1. 背景与目标

### 1.1 背景

V1.0.1 引入 ExecutionPipeline 装饰器链架构，V1.0.2/V1.0.3 验证 Pipeline 扩展性（RetryStage + CheckpointStage）。

ChatGPT 在 V1.0.3 代码审核（9.95/10）明确提出路线图：

> "Checkpoint 完成以后。我不会建议继续增强 Checkpoint。而应该进入 ConditionStage。因为目前 Pipeline 已经有 Route / Retry / Metrics / Checkpoint。下一步真正缺的是 Workflow Control。"

### 1.2 目标

本 ADR 引入 **ConditionStage**，让 Pipeline 真正成为 **Workflow Runtime**：

- **条件分支**：基于 ctx 字段做条件求值，决定后续 Stage 是否执行
- **跳过（skip）**：条件不满足时跳过后续 Stage（视为 Workflow 正常结束）
- **终止（abort）**：条件满足时设置 `ctx.stop = True`，主动终止 Pipeline
- **可观测**：Condition 求值结果写入 `ctx.metadata["condition_eval"]`（供后续 Stage 审计）

> **ChatGPT 9.9/10 Q3 关键澄清**：`skip` 和 `abort` 两者实现都是 `ctx.stop = True`，但语义不同：
> - `skip` = Workflow **正常结束**（如 "成功就跳过后续"）
> - `abort` = Workflow **被主动终止**（如 "失败就紧急停止"）
>
> ConditionStage 在 metadata 中写入 `stopped_by: "condition:skip"` / `"condition:abort"` 区分两者。CheckpointStage 看到 metadata 后会写入 `aborted: true` / `stopped_by: "condition"`。

### 1.3 非目标

- ❌ **不**做完整工作流引擎（Temporal / Airflow）
- ❌ **不**做 Task Graph / DAG 调度（V2）
- ❌ **不**做条件表达式 DSL（V1.0.4 仅 `callable(ctx) -> bool`）
- ❌ **不**做异步 Pipeline（V2）
- ❌ **不**做 Condition 链（V1.0.4 仅单 Condition；V1.1 评估 `conditions: list[Condition]`）

---

## 2. 设计原则

### 2.1 遵循 Runtime Contract §9.1.1 通用 Stage 约束

- Stage **MUST NOT** 修改 ExecutionContext 主体（仅在条件触发 abort 时设置 `ctx.stop = True`）
- Stage **MUST NOT** 接触 SQLiteExecutionStore / EventBus 内部，除非显式传入
- Stage 失败 **MUST** 返回有效 ctx（不抛异常，不污染主链路）

### 2.2 ChatGPT 9.95/10 关键建议

> "下一步真正缺的是 Workflow Control。V1.0.4 ConditionStage。Checkpoint 已经提供：恢复。Condition 再提供：分支。Workflow Runtime 就真正开始形成。"

**采纳**：ConditionStage 是"控制 Stage"，与"持久化 Stage"（Checkpoint）职责完全分离。

### 2.3 Core Freeze

- **0 修改** `core/`
- **0 修改** `router/router.py`
- **0 修改** `providers/`
- **0 修改** `planner/pipeline.py` 主体（仅 `default_pipeline()` 工厂加 `include_condition` 参数）
- **新增** `planner/stages/condition_stage.py`
- **新增** `tests/test_condition_stage.py`

### 2.4 ChatGPT 9.95/10 关键设计原则

> **Condition is a control boundary, not a data boundary.**

**含义**：
- Condition 负责：控制（control）— 决定是否继续 / 跳过 / 终止
- Condition 不负责：数据（data）— 不修改 ctx.task / ctx.bridge_result
- 执行还是：Pipeline
- Condition 只是："如果条件满足，这里就停 / 跳。"

**重要性**：这一句话让 Condition 与 Checkpoint（持久化）和 Retry（重试）完全分离，三者各司其职。

### 2.5 ChatGPT 9.95/10 关键抽象原则

> **Condition is a callable, not a DSL.**

**含义**：
- V1.0.4 仅接受 `Callable[[ExecutionContext], bool]`
- **不**做 DSL 表达式（`bridge_result.success == True`）
- **不**做 JSON Schema 条件
- 用户在 Python 代码里写 `lambda ctx: ctx.bridge_result.success`
- 未来 V1.1+ 可扩展 DSL（基于 Lark / lark-cli 等）

**理由**：
- Callable 简单、明确、可测试
- DSL 增加复杂度（解析器、错误处理、Schema 演进）
- V1.0.4 优先证明 Workflow Control 概念，不展开 DSL

### 2.6 ChatGPT 9.95/10 Failure 原则

> **Condition 异常 → 视为条件不满足（fail-closed），不抛异常。**

**含义**：
- Condition callable 抛异常 → logger.warning → 条件视为 False → 继续执行
- 不允许：Condition 异常 → Pipeline FAIL
- Condition 是软控制，不是硬关卡

**理由**：
- Best Effort 与 Checkpoint / Retry 一致
- 单一 Condition 失败不应阻塞整个 Pipeline

---

## 3. API 设计

### 3.1 `Condition` 类型

```python
from typing import Callable
from planner.pipeline import ExecutionContext

Condition = Callable[[ExecutionContext], bool]
```

简单、明确、可测试。

### 3.2 `ConditionStage` 类

```python
class ConditionStage:
    """Post-bridge Stage: 条件分支 / 跳过 / 终止.
    
    关键不变量 (Runtime Contract §9.1.5):
      - 0 修改 ExecutionContext 主体 (仅在 abort 时设 ctx.stop)
      - Condition 异常 → fail-closed (视为条件不满足, 继续执行)
      - Stage 异常 → 视为 Stage 失败 → pass (Best Effort)
    
    Stage 顺序 (默认):
      [RetryStage, MetricsStage, ConditionStage, CheckpointStage]
      - Condition 在 Checkpoint 前: Condition 先写 metadata
      - Condition 在 Metrics 后: 终止决策基于最终结果
      - **Checkpoint 总是写** (ChatGPT 9.9/10 Q4 关键采纳): 即使 abort 也要写 Checkpoint,
        记录 status=aborted / stopped_by=condition (Runtime Observability)
    """
    
    def __init__(
        self,
        condition: Condition,
        on_true: Literal["continue", "skip", "abort"] = "continue",
        on_false: Literal["continue", "skip", "abort"] = "continue",
        name: str = "condition",
    ):
        if condition is None:
            raise ValueError("ConditionStage requires a non-None condition")
        if on_true not in ("continue", "skip", "abort"):
            raise ValueError(...)
        ...
        self.condition = condition
        self.on_true = on_true
        self.on_false = on_false
        self._name = name  # ChatGPT 9.9/10 Q6 采纳: name 注入
    
    @property
    def name(self) -> str:
        return self._name
    
    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        """求值 condition, 按 on_true/on_false 决定动作."""
        # Best Effort: 短路 — 已被终止 / 缺 task / 缺 bridge_result
        if ctx.stop or ctx.task is None or ctx.bridge_result is None:
            return ctx
        
        # 1. 求值 (fail-closed)
        try:
            result = self.condition(ctx)
        except Exception as e:
            logger.warning(
                "ConditionStage condition raised exception for task %s: %s. "
                "Treating as False (fail-closed).",
                ctx.task.task_id, e,
            )
            result = False
        
        # 2. 选择动作
        action = self.on_true if result else self.on_false
        
        # 3. 记录审计 (供后续 Stage / Checkpoint 看到)
        if not hasattr(ctx, "metadata") or ctx.metadata is None:
            ctx.metadata = {}
        ctx.metadata["condition_eval"] = {
            "stage": "condition",
            "condition_name": self._name,  # ChatGPT 9.9/10 Q6 采纳
            "result": bool(result),
            "action": action,
            "timestamp": time.time(),
        }
        
        # 4. 执行动作
        if action == "skip":
            ctx.stop = True  # 跳过后续 stage, 视为终止
            ctx.metadata["condition_eval"]["stopped_by"] = "condition:skip"
        elif action == "abort":
            ctx.stop = True
            ctx.metadata["condition_eval"]["stopped_by"] = "condition:abort"
        # else: continue, pass
        
        return ctx
```

### 3.3 `default_pipeline()` 工厂

```python
def default_pipeline(
    router, quota=None,
    include_metrics=True,
    include_retry=False,
    include_condition=False,  # V1.0.4 新增
    condition=None,           # V1.0.4 新增
    condition_actions=("continue", "continue"),  # V1.0.4 新增
    include_checkpoint=False,
    execution_store=None,
):
    pre_bridge = [RouteStage(router)]
    post_bridge = []
    if include_retry:
        from planner.stages.retry_stage import RetryStage
        post_bridge.append(RetryStage())
    if include_metrics:
        post_bridge.append(MetricsStage())
    if include_condition:
        from planner.stages.condition_stage import ConditionStage
        if condition is None:
            raise ValueError("default_pipeline(include_condition=True) requires condition")
        post_bridge.append(ConditionStage(
            condition=condition,
            on_true=condition_actions[0],
            on_false=condition_actions[1],
        ))
    if include_checkpoint:
        from planner.stages.checkpoint_stage import CheckpointStage
        if execution_store is None:
            raise ValueError("default_pipeline(include_checkpoint=True) requires execution_store")
        post_bridge.append(CheckpointStage(execution_store))
    return ExecutionPipeline(...)
```

### 3.4 `PlanExecutor` 透传

```python
class PlanExecutor:
    def __init__(
        self,
        router, quota=None,
        include_metrics=True,
        include_retry=False,
        include_condition=False,    # V1.0.4 新增
        condition=None,             # V1.0.4 新增
        condition_actions=("continue", "continue"),  # V1.0.4 新增
        include_checkpoint=False,
        execution_store=None,
    ):
        self._pipeline_factory = lambda: default_pipeline(
            router, quota=quota,
            include_metrics=include_metrics,
            include_retry=include_retry,
            include_condition=include_condition,
            condition=condition,
            condition_actions=condition_actions,
            include_checkpoint=include_checkpoint,
            execution_store=execution_store,
        )
```

---

## 4. 关键决策

### 决策 #1：Stage 顺序 — Condition 在 Checkpoint 前 + Checkpoint 总是写

**理由**（ChatGPT 9.9/10 Q4 关键采纳）：
- **Checkpoint 总是写**：即使 Condition 触发 abort/skip, Checkpoint 也要写
  - 原因：Workflow 被终止也是 Runtime 的一个事实
  - 恢复时需要知道为什么结束
  - 符合 Runtime Observability
- **Condition 在 Checkpoint 前**：Condition 先写 `ctx.metadata["condition_eval"]`
  - Checkpoint 看到 metadata 后写入 `aborted: true` / `stopped_by: "condition"`
- **Condition 在 Metrics 后**：终止决策基于最终结果（含重试后 / metrics 注入后）
- Stage 顺序：`[RetryStage, MetricsStage, ConditionStage, CheckpointStage]`

**拒绝方案**：Condition 终止时不写 Checkpoint
- 恢复时不知道 Workflow 为何结束
- 违反 Runtime Observability

**CheckpointStage 行为调整**（V1.0.4 同步）：
- 移除 `ctx.stop` 短路（仅短路 `task=None` / `bridge_result=None`）
- 即使 `ctx.stop=True` 也要写 Checkpoint（记录 abort 事实）
- CheckpointSnapshot 增加 `aborted: bool` / `stopped_by: Optional[str]` 字段

### 决策 #2：单 Condition 而非 Condition 链

**理由**：
- V1.0.4 优先证明 Workflow Control 概念
- 链（conditions: list[Condition]）是 V1.1 评估范围
- 单 Condition 已经覆盖 90% 用例（"成功就继续 / 失败就终止"）

**拒绝方案**：DSL 表达式（`bridge_result.success == True`）
- 增加复杂度（解析器、错误处理、Schema 演进）
- V1.0.4 用 `lambda ctx: ctx.bridge_result.success` 就够

### 决策 #3：fail-closed（异常视为 False）

**理由**：
- Best Effort 与 Checkpoint / Retry 一致
- 单一 Condition 失败不应阻塞整个 Pipeline
- 用户可以在 Condition callable 内部加 try/except 自主处理

**拒绝方案**：fail-open（异常视为 True）
- 可能让有 bug 的 Condition 误触发终止

### 决策 #4：审计写入 ctx.metadata

**理由**：
- Condition 求值结果供后续 Stage 看到（特别是 Checkpoint）
- 不引入新的 ctx 字段
- 复用 Metadata 机制（Runtime Contract §5.2）

**拒绝方案**：新增 ctx.condition_eval
- 加 ctx 字段增加 API 复杂度
- Metadata 已经够用

### 决策 #5：0 修改 Pipeline 主体

**理由**：
- 与 V1.0.1 / V1.0.2 / V1.0.3 一致
- `default_pipeline()` 工厂加 3 参数，主体 0 行为变化

---

## 5. 关键边界 / 失败模式

### 5.1 短路条件

- `ctx.stop = True` → 直接 pass（已被前面的 Stage 终止）
- `ctx.task is None` → pass
- `ctx.bridge_result is None` → pass

### 5.2 Condition 异常

```python
# 1. Condition callable 抛异常
try:
    result = self.condition(ctx)
except Exception as e:
    logger.warning(...)
    result = False  # fail-closed
```

### 5.3 Stage 自身异常

```python
# 1. __call__ 抛异常
try:
    ...
except Exception as e:
    logger.warning(...)
    return ctx  # Best Effort: pass
```

### 5.4 审计写入失败

- `ctx.metadata` 写入失败 → logger.warning → 继续执行
- 审计失败不影响 Condition 主决策

---

## 6. 测试策略

### 6.1 单元测试 (TestConditionSnapshot / TestConditionStage)

- `test_init_requires_condition` — 缺 condition → ValueError
- `test_init_invalid_action` — on_true/on_false 非合法值 → ValueError
- `test_short_circuit_on_no_task` — ctx.task=None → pass
- `test_short_circuit_on_no_bridge_result` — ctx.bridge_result=None → pass
- `test_short_circuit_on_stop` — ctx.stop=True → pass
- `test_condition_true_continue` — condition=True, on_true="continue" → ctx 保持, condition_eval.result=True
- `test_condition_false_continue` — condition=False, on_false="continue" → ctx 保持
- `test_condition_true_abort` — condition=True, on_true="abort" → ctx.stop=True
- `test_condition_false_abort` — condition=False, on_false="abort" → ctx.stop=True
- `test_condition_true_skip` — condition=True, on_true="skip" → ctx.stop=True (skip 视为终止)
- `test_condition_false_skip` — condition=False, on_false="skip" → ctx.stop=True
- `test_condition_exception_fail_closed` — condition 抛异常 → 视为 False → 继续
- `test_condition_metadata_written` — ctx.metadata["condition_eval"] 写入
- `test_condition_does_not_modify_task` — ctx.task 不变
- `test_condition_does_not_modify_bridge_result` — ctx.bridge_result 不变

### 6.2 Pipeline 集成测试 (TestConditionPipelineIntegration)

- `test_pipeline_with_condition_continue` — condition=True → Pipeline 完整执行
- `test_pipeline_with_condition_abort` — condition=True, on_true="abort" → Pipeline 终止
- `test_pipeline_with_condition_skip` — condition=True, on_true="skip" → Pipeline 终止
- `test_pipeline_with_condition_and_checkpoint` — **Condition 终止 → Checkpoint 仍写**（ChatGPT 9.9/10 Q4 关键调整）
  - CheckpointSnapshot.aborted = True
  - CheckpointSnapshot.stopped_by = "condition"
- `test_pipeline_with_condition_and_retry` — Retry + Condition 组合

### 6.3 边界测试 (TestConditionStageChatGPTEdgeCases)

- `test_complex_condition_callable` — 复杂 condition（含多字段）
- `test_condition_with_metrics_metadata` — condition 读取 MetricsStage 注入的 server_metrics
- `test_condition_called_only_once` — condition callable 只调用一次
- `test_metadata_persists_across_stages` — condition_eval 写入后被 Checkpoint 看到
- `test_pipeline_executor_passes_condition` — PlanExecutor 透传 condition
- `test_default_pipeline_requires_condition` — default_pipeline(include_condition=True) 缺 condition → ValueError
- `test_condition_name_in_metadata` — name 注入 → metadata.condition_eval.condition_name
- `test_skip_vs_abort_stopped_by_differs` — skip 写 "condition:skip", abort 写 "condition:abort"
- `test_condition_metadata_overwrite_on_repeat` — **ChatGPT 9.9/10 Q8 采纳**: 连续两次 Condition → metadata 覆盖（不追加）
- `test_checkpoint_records_aborted_metadata` — **ChatGPT 9.9/10 Q8 采纳**: Condition abort → Checkpoint snapshot.aborted=True, stopped_by="condition"

---

## 7. Runtime Contract 同步

新增 §9.1.5 ConditionStage 专属约束：

```markdown
### §9.1.5 ConditionStage

ConditionStage MUST:
- 接受 `Callable[[ExecutionContext], bool]` 作为条件
- 在 condition 为 True 时按 on_true 决定动作（continue/skip/abort）
- 在 condition 为 False 时按 on_false 决定动作（continue/skip/abort）
- 在 action="skip" 或 "abort" 时设置 `ctx.stop = True`
- 在 condition 抛异常时视为 False (fail-closed)
- 在 Stage 自身抛异常时返回原 ctx (Best Effort)
- 将求值结果写入 `ctx.metadata["condition_eval"]` (供后续 Stage 看到)
- **`condition` MUST be deterministic for the same ExecutionContext** (ChatGPT 9.9/10 Q10 采纳)
  - 不应使用 random() / time() / network() / sleep()
  - 否则 Checkpoint Replay 可能不一致

ConditionStage MUST NOT:
- 修改 ctx.task / ctx.bridge_result / ctx.provider
- 接触 SQLiteExecutionStore / EventBus 内部 (除非显式传入)
- 抛异常
- 引入新的 ctx 字段

ConditionStage SHOULD:
- **避免外部可观测副作用** (ChatGPT 9.95/10 Q10 采纳)
  - 最好: 读 Context → 返回 bool
  - 避免: 写数据库 / 发网络 / 修改文件
  - 否则: Replay 不可预测
```

---

## 8. 未来扩展 (V1.1+)

### V1.1: Condition 链

```python
class ConditionStage:
    def __init__(
        self,
        conditions: list[Condition],  # V1.1: list 而非单个
        on_true: str = "continue",
        on_false: str = "continue",
    ):
        ...
```

### V1.1: DSL 表达式

```python
from planner.dsl import parse_condition
condition = parse_condition("bridge_result.success == True")
```

### V1.1: Condition 模板

```python
class ConditionTemplates:
    @staticmethod
    def on_success() -> Condition: ...
    @staticmethod
    def on_failure() -> Condition: ...
    @staticmethod
    def on_metric(name: str, op: str, value: Any) -> Condition: ...
```

---

## 9. 确认问题

1. **API 命名**：`ConditionStage` / `condition_eval` / `on_true` / `on_false` 是否清晰？
2. **Stage 顺序**：Condition 在 Checkpoint 前是否合理？
3. **fail-closed**：异常视为 False 是否合理？是否需要 fail-open 选项？
4. **审计机制**：`ctx.metadata["condition_eval"]` 是否够用？是否需要独立 ctx 字段？
5. **DSL 推迟**：V1.0.4 不做 DSL 是否可接受？V1.1 评估。
6. **Condition 链推迟**：V1.0.4 不做链是否可接受？V1.1 评估。
7. **默认值**：`on_true="continue"`, `on_false="continue"` 是否合理？还是应该根据常见用例调整？
8. **测试覆盖**：15 单元 + 5 集成 + 6 边界 = 26 tests，是否够？
