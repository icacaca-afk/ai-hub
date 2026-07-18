# ChatGPT ADR 审核 prompt — ADR-0025 V1.0.5 PipelineHooks 草案

## 背景

ai-hub 项目 V1.0.5 PipelineHooks 草案已写好，请审核 ADR 设计。

- **ADR**: [0025-pipeline-hooks.md](https://...) (Proposed, 待审)
- **前序 ChatGPT 路线图**: V1.0.4 代码审核 9.95/10 — "**V1.0.5 Pipeline Hooks**（before/after），便于日志、Tracing、调试"
- **依赖**: ADR-0021 / 0022 / 0023 / 0024 (均已 Accepted)
- **目标**: 让 Pipeline 真正成为可观察的 Runtime — 6 类生命周期 Hook (before/after pipeline/stage + on_error/on_stop)

## 关键设计

### 1. 抽象原则 (ChatGPT 9.95/10 关键)

> **Hook is an observer, not a Stage.**

- Hook 关注: 生命周期事件 (Lifecycle Events)
- Hook 不关注: 数据 / 业务逻辑 / 控制流
- 与 Stage 的区别:
  - Stage: 修改 ctx (Route, Retry, Metrics, Condition, Checkpoint)
  - Hook: 不修改 ctx (V1.0.5 仅观察)

### 2. 6 类 Hook 点

```python
BeforePipelineHook = Callable[[ExecutionContext], None]
AfterPipelineHook = Callable[[ExecutionContext, Result], None]
BeforeStageHook = Callable[[ExecutionContext, str], None]  # (ctx, stage_name)
AfterStageHook = Callable[[ExecutionContext, str], None]
OnErrorHook = Callable[[ExecutionContext, str, Exception], None]
OnStopHook = Callable[[ExecutionContext, str], None]  # (ctx, stopped_by)
```

- V1.0.5 仅 `Callable[..., None]` 形式
- **不**支持 Modify Hook (返回修改后的 ctx)
- 未来 V1.1 评估 Modify Hook

### 3. List[Hook] 形式

```python
class PipelineHooks:
    def __init__(
        self,
        before_pipeline: list[BeforePipelineHook] = None,
        after_pipeline: list[AfterPipelineHook] = None,
        before_stage: list[BeforeStageHook] = None,
        after_stage: list[AfterStageHook] = None,
        on_error: list[OnErrorHook] = None,
        on_stop: list[OnStopHook] = None,
    ):
        ...
```

- 用户可注册多个 Hook (日志 + Tracing + Metrics)
- FIFO 顺序
- V1.0.5 不支持优先级

### 4. Best Effort (关键)

```python
def fire_before_stage(self, ctx, stage_name):
    for hook in self.before_stage:
        try:
            hook(ctx, stage_name)
        except Exception as e:
            logger.warning("before_stage hook raised: %s", e)
```

- Hook 异常 → 静默 (logger.warning, 继续)
- 不允许: Hook 异常 → Pipeline FAIL
- 与 Stage / Condition / Checkpoint 的 Best Effort 一致

### 5. Core Freeze

- **0 修改** `core/`
- **0 修改** `router/router.py`
- **0 修改** `providers/`
- **修改** `planner/pipeline.py` Pipeline 主体 (增加 ~10 行 hook 调用代码, Stage 行为不变)
- **新增** `planner/hooks.py`
- **新增** `tests/test_pipeline_hooks.py`

### 6. Pipeline.run() 集成 (关键)

```python
class ExecutionPipeline:
    def run(self, task: Task) -> Result:
        ctx = ExecutionContext(task=task)
        
        # V1.0.5: Hook before_pipeline
        if not self.hooks.is_empty():
            self.hooks.fire_before_pipeline(ctx)
        
        # 1. Pre-bridge stages
        for stage in self.pre_bridge_stages:
            self.hooks.fire_before_stage(ctx, stage.name)
            try:
                ctx = stage(ctx)
            except Exception as e:
                self.hooks.fire_on_error(ctx, stage.name, e)
                raise  # V1.0.5: 异常仍然 throw (Hook 仅观察)
            self.hooks.fire_after_stage(ctx, stage.name)
            if ctx.stop:
                self.hooks.fire_on_stop(ctx, "stop_flag")
                ...
        
        # 2. Base execute
        # 3. Post-bridge stages (同样模式)
        
        # V1.0.5: Hook after_pipeline
        result = PipelineExecutor.assemble_result(ctx)
        if not self.hooks.is_empty():
            self.hooks.fire_after_pipeline(ctx, result)
        return result
```

### 7. default_pipeline() 工厂 + PlanExecutor 透传

```python
def default_pipeline(
    ...,
    hooks: PipelineHooks = None,  # V1.0.5 新增
):
    return ExecutionPipeline(
        ...,
        hooks=hooks,
    )

class PlanExecutor:
    def __init__(
        self,
        ...,
        hooks: PipelineHooks = None,  # V1.0.5 新增
    ):
        ...
```

## 关键约束 (Runtime Contract §9.1.6)

**PipelineHooks MUST**:
- 接受 6 类 Hook callable
- 在 hook 抛异常时静默 (Best Effort, logger.warning)
- 在 Pipeline.run 主体增加 hook 调用点
- 0 修改 Stage 行为 (仅在 Stage 前后 fire_xxx)
- 在 hook 列表为空时跳过调用 (性能优化 is_empty())

**PipelineHooks MUST NOT**:
- 修改 ExecutionContext (V1.0.5 仅观察)
- 接触 SQLiteExecutionStore / EventBus 内部
- 抛异常
- 影响 Stage 行为

## 关键决策

| # | 决策 | 理由 |
|---|------|------|
| #1 | Hook 是 List[Hook] | 用户可组合多 Hook (日志+Tracing) |
| #2 | Hook 不修改 ctx (V1.0.5) | 避免 Hook 演化成"伪 Stage" |
| #3 | Hook 失败 Best Effort | 与 Stage 一致 |
| #4 | 0 修改 Stage 行为 | 仅增加 hook 调用点 |
| #5 | 6 个 Hook 点 | 平衡"够用"和"复杂度" |

## 未来扩展 (V1.1+)

- V1.1 Modify Hook
- V1.1 Hook 优先级
- V1.1 Tracing / OpenTelemetry 集成
- V1.1 stop_reason 统一 metadata

## 关键确认问题

1. **6 个 Hook 点**是否够？是否需要 before_each_retry？
2. **Hook 不修改 ctx**是否合理？是否需要 Modify Hook (V1.0.5)？
3. **Hook 失败 Best Effort**是否合理？是否需要 fail-strict 选项？
4. **Hook 顺序 FIFO**是否够？是否需要 priority？
5. **List[Hook] 形式**是否合理？是否需要 HookContext？
6. **测试覆盖**：8 单元 + 3 失败 + 4 集成 + 4 边界 = 19 tests，是否够？
7. **Performance**：6 个 hook 调用点 + is_empty 检测，是否影响性能？
8. **Stage Hook**：before_stage/after_stage 是否需要 ctx.stop 检查？

## 审核问题

**Q1 架构**: Hook 作为独立抽象 (不是 Stage) 是否正确？是否应该把 Hook 整合到 Stage 接口？

**Q2 6 个 Hook 点**: 是否够？是否过度设计？是否需要 before_retry / after_retry (Retry 特定)？

**Q3 Hook 不修改 ctx (V1.0.5)**: 是否合理？是否应该在 V1.0.5 就支持 Modify Hook？

**Q4 List[Hook] 形式**: 是否够？是否应该用 HookProvider (单个) + HookChain (多个) 分离？

**Q5 Best Effort**: Hook 异常静默是否合理？是否需要 hook_error_policy 参数 (LOG_ONLY / RAISE / IGNORE)？

**Q6 Core Freeze**: 修改 Pipeline.run() (~10 行) 是否破坏"Pipeline 主体 0 行为变化"原则？0 修改 core/router/providers 是否合理？

**Q7 Performance**: 6 个 hook 调用点 + is_empty() 检查，是否影响 V1.0.x 性能 (每个 Pipeline.run 跑 1000 次)？

**Q8 测试覆盖**: 19 tests (8+3+4+4) 是否足够？是否需要 Tracing / OpenTelemetry 集成测试？

**Q9 未来扩展**: V1.1 Modify Hook / priority / Tracing 推迟是否合理？是否会限制用户场景？

**Q10 Runtime Contract §9.1.6**: 5 MUST + 4 MUST NOT 是否完整？是否需要"Hook 顺序 FIFO" 显式 MUST？

**Q11 整体评分**: 9.5+/10 评分依据。

## 期望

- 综合评分 ≥ 9.5/10
- 阻塞性调整: 0-1 项
- 非阻塞性建议: 任意
- 明确 APPROVED / NEEDS REVISION

## 风格指南

按 V1.0.2 (9.9/10) / V1.0.3 (9.9/10 ADR / 9.95/10 代码) / V1.0.4 (9.9/10 ADR / 9.95/10 代码) 标准：
- 直接给评分 + 分项
- 引用具体 ADR 节号
- 拒绝方案时说明"为什么 X 比 Y 好"
- 路线图强建议
