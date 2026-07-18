# ADR-0025: PipelineHooks — Pipeline 生命周期观察 (before/after)

- **里程碑**: V1.0.5
- **作者**: ai-hub core team
- **日期**: 2026-07-18
- **状态**: Accepted（[ChatGPT 9.9/10 FINAL APPROVED](../reviews/0025-adr-chatgpt-review.md)）
- **依赖**: [ADR-0021 ExecutionPipeline](0021-execution-pipeline.md), [ADR-0022 RetryStage](0022-retry-stage.md), [ADR-0023 CheckpointStage](0023-checkpoint-stage.md), [ADR-0024 ConditionStage](0024-condition-stage.md)
- **前序 ChatGPT 路线图**: V1.0.4 代码审核 9.95/10 FINAL — "**V1.0.5 Pipeline Hooks**（before/after），便于日志、Tracing、调试"

> **Pipeline Hooks 是观察者，不是 Stage.**
> Hooks 关注: 生命周期事件 (Lifecycle Events).
> Hooks 不关注: 数据 / 业务逻辑 / 控制流.

---

## 1. 背景与目标

### 1.1 背景

V1.0.1 - V1.0.4 已经建立了完整的 Pipeline 架构（4 个 Stage: Retry / Metrics / Condition / Checkpoint）。

ChatGPT 在 V1.0.4 代码审核（9.95/10）明确提出路线图：

> "我建议下一步不要再增加新的 Stage 类型，而是开始完善 Runtime 的能力。优先级建议：V1.0.5 Pipeline Hooks（before/after），便于日志、Tracing、调试。"

### 1.2 目标

本 ADR 引入 **PipelineHooks**，让 Pipeline 真正成为 **可观察的 Runtime**：

- **生命周期事件**：before_pipeline / after_pipeline / before_stage / after_stage
- **错误捕获**：on_error 捕获 Stage 异常
- **终止捕获**：on_stop 捕获 ctx.stop 事件
- **可组合**：List[Hook] 多个 Hook 同时存在
- **Best Effort**：Hook 失败不阻塞主链路

### 1.3 非目标

- ❌ **不**做 Tracing / OpenTelemetry 集成（V1.1 评估）
- ❌ **不**做 Metrics 收集（V0.9.x MetricsStage 已做）
- ❌ **不**做 Logger 配置（沿用 stdlib logging）
- ❌ **不**做 Hook 优先级 / 顺序（V1.0.5 仅 FIFO 顺序）
- ❌ **不**做 Hook 返回值传播（V1.0.5 Hook 仅观察，不修改 ctx）

---

## 2. 设计原则

### 2.1 遵循 Runtime Contract §9.1.1 通用 Stage 约束

- Hook **MUST NOT** 修改 ctx（V1.0.5 仅观察，不修改）
- Hook **MUST NOT** 接触 SQLiteExecutionStore / EventBus 内部
- Hook 失败 **MUST** 静默 (Best Effort, logger.warning)

### 2.2 ChatGPT 9.95/10 关键建议

> "Pipeline Hooks（before/after），便于日志、Tracing、调试。"

**采纳**：Hooks 是 Runtime 的"事件监听器"，与 Stage 互补。

### 2.3 Core Freeze

- **0 修改** `core/`
- **0 修改** `router/router.py`
- **0 修改** `providers/`
- **0 修改** `planner/pipeline.py` Pipeline 主体逻辑（仅在 Stage 前后加 hook 调用点）
- **修改** `planner/pipeline.py` Pipeline 主体（增加 ~10 行 hook 调用代码）
- **新增** `planner/hooks.py`
- **新增** `tests/test_pipeline_hooks.py`

### 2.4 ChatGPT 9.95/10 关键抽象原则

> **Hook is an observer, not a Stage.**

**含义**：
- Hook 关注：生命周期事件
- Hook 不关注：数据 / 业务逻辑
- Hook 与 Stage 的区别：
  - Stage: 修改 ctx（Route, Retry, Metrics, Condition, Checkpoint）
  - Hook: 不修改 ctx（仅观察）

**重要性**：这一句话让 Hook 与 Stage 完全分离，避免 Hook 演化成"伪 Stage"。

### 2.5 ChatGPT 9.95/10 Failure 原则

> **Hook 异常 → 静默 (Best Effort), 不影响主链路.**

**含义**：
- Hook callable 抛异常 → logger.warning → 继续
- 不允许：Hook 异常 → Pipeline FAIL
- Hook 是观察者，**不应该**因为观察失败而影响业务

---

## 3. API 设计

### 3.1 `Hook` 类型

```python
from typing import Callable
from planner.pipeline import ExecutionContext
from core.result import Result

# Before Pipeline Hook (整体执行前)
BeforePipelineHook = Callable[[ExecutionContext], None]

# After Pipeline Hook (整体执行后, 含 Result)
AfterPipelineHook = Callable[[ExecutionContext, Result], None]

# Before Stage Hook (每个 Stage 前)
BeforeStageHook = Callable[[ExecutionContext, str], None]  # (ctx, stage_name)

# After Stage Hook (每个 Stage 后)
AfterStageHook = Callable[[ExecutionContext, str], None]  # (ctx, stage_name)

# On Error Hook (Stage 异常时)
OnErrorHook = Callable[[ExecutionContext, str, Exception], None]  # (ctx, stage_name, exc)

# On Stop Hook (ctx.stop 触发时)
OnStopHook = Callable[[ExecutionContext, str], None]  # (ctx, stopped_by)
```

V1.0.5 仅 `Callable[..., None]` 形式，不支持修改 ctx 的 Hook。

### 3.2 `PipelineHooks` 类

```python
class PipelineHooks:
    """V1.0.5: Pipeline 生命周期观察器 (Best Effort)."""
    
    def __init__(
        self,
        before_pipeline: list[BeforePipelineHook] = None,
        after_pipeline: list[AfterPipelineHook] = None,
        before_stage: list[BeforeStageHook] = None,
        after_stage: list[AfterStageHook] = None,
        on_error: list[OnErrorHook] = None,
        on_stop: list[OnStopHook] = None,
    ):
        self.before_pipeline = list(before_pipeline or [])
        self.after_pipeline = list(after_pipeline or [])
        self.before_stage = list(before_stage or [])
        self.after_stage = list(after_stage or [])
        self.on_error = list(on_error or [])
        self.on_stop = list(on_stop or [])
    
    def fire_before_pipeline(self, ctx: ExecutionContext) -> None:
        """触发 before_pipeline hooks (Best Effort)."""
        for hook in self.before_pipeline:
            try:
                hook(ctx)
            except Exception as e:
                logger.warning("before_pipeline hook raised: %s", e)
    
    def fire_after_pipeline(self, ctx: ExecutionContext, result: Result) -> None:
        for hook in self.after_pipeline:
            try:
                hook(ctx, result)
            except Exception as e:
                logger.warning("after_pipeline hook raised: %s", e)
    
    def fire_before_stage(self, ctx: ExecutionContext, stage_name: str) -> None:
        for hook in self.before_stage:
            try:
                hook(ctx, stage_name)
            except Exception as e:
                logger.warning("before_stage hook raised: %s", e)
    
    def fire_after_stage(self, ctx: ExecutionContext, stage_name: str) -> None:
        for hook in self.after_stage:
            try:
                hook(ctx, stage_name)
            except Exception as e:
                logger.warning("after_stage hook raised: %s", e)
    
    def fire_on_error(self, ctx: ExecutionContext, stage_name: str, exc: Exception) -> None:
        for hook in self.on_error:
            try:
                hook(ctx, stage_name, exc)
            except Exception as e:
                logger.warning("on_error hook raised: %s", e)
    
    def fire_on_stop(self, ctx: ExecutionContext, stopped_by: str) -> None:
        for hook in self.on_stop:
            try:
                hook(ctx, stopped_by)
            except Exception as e:
                logger.warning("on_stop hook raised: %s", e)
    
    def is_empty(self) -> bool:
        return all([
            not self.before_pipeline,
            not self.after_pipeline,
            not self.before_stage,
            not self.after_stage,
            not self.on_error,
            not self.on_stop,
        ])
```

### 3.3 `ExecutionPipeline` 集成

```python
class ExecutionPipeline:
    def __init__(
        self,
        router: Router,
        pre_bridge_stages: list[Stage] = None,
        post_bridge_stages: list[Stage] = None,
        quota: Any = None,
        hooks: PipelineHooks = None,  # V1.0.5 新增
    ):
        ...
        self.hooks = hooks or PipelineHooks()
    
    def run(self, task: Task) -> Result:
        # Hook: before_pipeline
        if not self.hooks.is_empty():
            self.hooks.fire_before_pipeline(ctx)
        
        # ... (Stage 循环中 fire_before_stage / fire_after_stage)
        
        # Hook: after_pipeline
        if not self.hooks.is_empty():
            self.hooks.fire_after_pipeline(ctx, result)
        
        return result
```

### 3.4 `default_pipeline()` 工厂

```python
def default_pipeline(
    router: Router,
    quota: Any = None,
    include_metrics: bool = True,
    include_retry: bool = False,
    include_condition: bool = False,
    condition: Any = None,
    condition_on_true: str = "continue",
    condition_on_false: str = "continue",
    condition_name: str = "condition",
    include_checkpoint: bool = False,
    execution_store: Any = None,
    hooks: PipelineHooks = None,  # V1.0.5 新增
):
    ...
    return ExecutionPipeline(
        router=router,
        pre_bridge_stages=pre_bridge,
        post_bridge_stages=post_bridge,
        quota=quota,
        hooks=hooks,
    )
```

### 3.5 `PlanExecutor` 透传

```python
class PlanExecutor:
    def __init__(
        self,
        ...,
        hooks: PipelineHooks = None,  # V1.0.5 新增
    ):
        ...
        self.pipeline = pipeline or default_pipeline(
            ...,
            hooks=hooks,
        )
```

---

## 4. 关键决策

### 决策 #1：Hook 是 List[Hook]，不是 Single Hook

**理由**：
- 用户可能有多个 Hook（日志 + Tracing + Metrics）
- List 天然支持组合
- 简单 API: `PipelineHooks(before_stage=[log_hook, trace_hook])`

**拒绝方案**：Single Hook
- 不支持组合，用户需自己写 aggregator
- 不符合 "Hook 简单、灵活" 原则

### 决策 #2：Hook 不修改 ctx (V1.0.5)

**理由**：
- ChatGPT §2.4: "Hook is an observer, not a Stage"
- V1.0.5 简化 API
- 未来 V1.1 可扩展"Modify Hook"（但这是更复杂的协议）

**拒绝方案**：Hook 返回修改后的 ctx
- 增加复杂度（每次需要返回 ctx）
- 容易让 Hook 演化成"伪 Stage"
- 违反 ChatGPT 关键原则

### 决策 #3：Hook 失败 Best Effort

**理由**：
- 与 Stage / Condition / Checkpoint 的 Best Effort 一致
- Hook 失败不应该影响业务
- 简单实现: `try/except + logger.warning`

**拒绝方案**：Hook 失败抛异常
- 不符合 Best Effort
- Hook 失败意味着观察失败，不应该影响业务

### 决策 #4：0 修改 Stage 调用逻辑（仅增加 hook 调用点）

**理由**：
- Stage 主体 0 行为变化
- Pipeline.run() 主体仍负责 Stage 循环
- Hook 仅作为"事件触发器"嵌入

**拒绝方案**：Hook 作为 Stage 装饰器
- 增加复杂度
- 引入新概念（装饰器）
- Stage 已经够多，不需要装饰器

### 决策 #5：6 个 Hook 点（不多不少）

| Hook | 触发时机 | 用途 |
|------|---------|------|
| before_pipeline | Pipeline.run 入口 | 初始化日志 / Tracing |
| after_pipeline | Pipeline.run 出口 | 收尾日志 / Tracing / Metrics |
| before_stage | Stage 执行前 | Stage 级日志 / Timing 开始 |
| after_stage | Stage 执行后 | Stage 级日志 / Timing 结束 |
| on_error | Stage 异常时 | 异常日志 / Alert |
| on_stop | ctx.stop 触发时 | 终止原因记录 |

**拒绝方案**：更少 Hook (e.g. 只有 before/after)
- 缺少错误捕获
- 缺少 Stage 级 Tracing

**拒绝方案**：更多 Hook (e.g. before_each_attempt)
- 复杂度爆炸
- V1.0.5 6 个够用

---

## 5. 关键边界 / 失败模式

### 5.1 Hook 异常

```python
try:
    hook(ctx)
except Exception as e:
    logger.warning("hook raised: %s", e)
    # 继续
```

### 5.2 Hook 数为 0 (无 Hook)

- `is_empty()` → True
- Pipeline.run() 检测 `is_empty()`，跳过 hook 调用（性能优化）

### 5.3 Hook 顺序

- 同一类 Hook 按 List 顺序执行（FIFO）
- V1.0.5 不支持优先级 / 顺序调整

---

## 6. 测试策略

### 6.1 单元测试 (TestPipelineHooks)

- `test_init_no_hooks` — 缺省空 hooks
- `test_init_with_hooks` — 各 hook 列表
- `test_fire_before_pipeline` — 调用 before_pipeline hooks
- `test_fire_after_pipeline` — 调用 after_pipeline hooks
- `test_fire_before_stage` — 调用 before_stage hooks
- `test_fire_after_stage` — 调用 after_stage hooks
- `test_fire_on_error` — 调用 on_error hooks
- `test_fire_on_stop` — 调用 on_stop hooks

### 6.2 失败处理 (TestPipelineHooksFailure)

- `test_hook_exception_best_effort` — hook 抛异常 → 静默
- `test_multiple_hooks_one_fails_others_continue` — 多 hook 一个失败，其他继续
- `test_is_empty` — 空 hooks 检测

### 6.3 Pipeline 集成 (TestPipelineHooksIntegration)

- `test_pipeline_with_hooks` — 完整 pipeline 跑，hooks 全部触发
- `test_pipeline_without_hooks` — 无 hooks, 不报错
- `test_hooks_called_in_order` — 多个 hook 按 List 顺序执行
- `test_pipeline_default_factory_passes_hooks` — default_pipeline(hooks=...) 透传

### 6.4 ChatGPT 边界 (TestPipelineHooksChatGPTEdgeCases)

- `test_hook_does_not_modify_ctx` — Hook 不修改 ctx (ChatGPT §2.4 关键)
- `test_on_stop_called_with_stopped_by` — on_stop 传入 stopped_by
- `test_on_error_called_with_exception` — on_error 传入 exception 对象
- `test_is_empty_with_partial_hooks` — 部分 hooks 非空时 is_empty 返回 False

---

## 7. Runtime Contract 同步

新增 §9.1.6 PipelineHooks 专属约束：

```markdown
### §9.1.6 PipelineHooks

PipelineHooks MUST:
- 接受 6 类 Hook callable (before/after pipeline/stage + on_error/on_stop)
- 在 hook 抛异常时静默 (Best Effort, logger.warning)
- 在 Pipeline.run 主体增加 hook 调用点
- 0 修改 Stage 行为 (仅在 Stage 前后 fire_xxx)
- 在 hook 列表为空时跳过调用 (性能优化 enabled 属性)
- **Hooks MUST be observational and MUST NOT participate in execution semantics** (ChatGPT 9.9/10 Q3 采纳)
- **Hook failures MUST NOT influence execution outcome** (ChatGPT 9.9/10 Q5 采纳)
  - 即使所有 hook 都失败, Pipeline 仍应正常执行

PipelineHooks SHOULD:
- **Hooks SHOULD execute in registration order (FIFO)** (ChatGPT 9.9/10 Q10 采纳)
  - V1.0.5 不支持 Priority
- **Hooks SHOULD be side-effect free whenever practical** (ChatGPT 9.9/10 Q10 采纳)
  - Tracing 可以写日志
  - 但不要: 删文件 / 改数据库 / 发请求
  - 原因: Runtime Replay 才稳定

PipelineHooks MUST NOT:
- 修改 ExecutionContext (V1.0.5 仅观察)
- 接触 SQLiteExecutionStore / EventBus 内部 (除非显式订阅)
- 抛异常
- 影响 Stage 行为
```

---

## 8. 未来扩展 (V1.1+)

### V1.1: Modify Hook

```python
ModifyBeforeStageHook = Callable[[ExecutionContext, str], ExecutionContext]
```

### V1.1: Hook 优先级

```python
class HookWithPriority:
    hook: Callable
    priority: int = 0
```

### V1.1: Tracing / OpenTelemetry 集成

```python
from planner.tracing import TracingHook

tracing_hook = TracingHook(tracer="otel")
pipeline = default_pipeline(router, hooks=PipelineHooks(before_stage=[tracing_hook.before]))
```

### V1.1: Stage 终止 metadata 统一为 stop_reason

```python
ctx.metadata["stop_reason"] = {
    "stage": "condition",
    "reason": "on_failure",
    "timestamp": 1234567890.0,
}
```

---

## 9. 确认问题

1. **6 个 Hook 点**是否够？是否需要 before_each_retry？
2. **Hook 不修改 ctx**是否合理？是否需要 Modify Hook？
3. **Hook 失败 Best Effort**是否合理？是否需要 fail-strict 选项？
4. **Hook 顺序 FIFO**是否够？是否需要 priority？
5. **List[Hook] 形式**是否合理？是否需要 HookContext（包含 ctx + stage_name + ...）？
6. **测试覆盖**：8 单元 + 3 失败 + 4 集成 + 4 边界 = 19 tests，是否够？
7. **Performance**：6 个 hook 调用点 + is_empty 检测，是否影响性能？
8. **Stage Hook**：before_stage/after_stage 是否需要 ctx.stop 检查？
