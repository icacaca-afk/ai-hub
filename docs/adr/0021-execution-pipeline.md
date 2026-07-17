# ADR-0021: V1.0.1 — ExecutionPipeline as Decorator / Middleware

- **状态**: Proposed
- **日期**: 2026-07-18
- **里程碑**: V1.0.1
- **关联**: ADR-0008（Core Freeze）、ADR-0009（HealthAwareRouter）、ADR-0011（ScoreRouter）、ADR-0019（Provider Metrics）、ADR-0020（Execution Analytics）、[Runtime Contract](../runtime-contract.md) §2 原则 F + §8 V0.9.6 临时层、[ARCHITECTURE.md §2.3](../ARCHITECTURE.md) V1.0 路线
- **API Stability**: Experimental
- **前序基线**: [V0.9.x → V1.0 整体收官总结](../reviews/v09x-to-v10-wrapup.md)
- **本版审核**: TBD（待 ChatGPT 外部审核）

## 背景

V0.9.x 收官后，Router 层的状态如下：

```
Router (router/router.py, Core Freeze)
  ↓ extends
HealthAwareRouter (router/health_router.py, V0.7)
  ↓ extends
ScoreRouter (router/score_router.py, V0.8)
  ↓ extends
MetricsRouter (router/metrics_router.py, V0.9.6 临时层)
```

每加一个**关注点**（health / score / metrics / future retry / future checkpoint），
都要写一个新 Router 子类，覆盖 `route()` 或 `execute()`，并把整段主链路复制一遍。

### 当前痛点

**1. Router 职责膨胀**

Router 类同时承担 3 个不同关注点：
- `route(task)` — 选 Provider（核心职责）
- `execute(task)` — 调 Bridge + 包装 Result（执行职责）
- 各子类扩展：health 过滤、score 排序、metrics 提取（新职责）

**2. 代码重复（V0.9.6 已知问题）**

`MetricsRouter.execute()` 把 `Router.execute()` 整段主链路（30+ 行）复制一遍，
仅在 `bridge.run()` 之后插入 `MetricsExtractor.extract()` 一行。
这意味着：
- 主链路任何修改都要同步到所有子类
- 子类化"装饰 execute()"本质上是手工 Decorator 模式
- 没有抽象层，每个新关注点都要复制粘贴

**3. 新关注点成本高**

V1.0 路线图上还有：
- ADR-0022 Retry Policy（失败重试）
- ADR-0023 Checkpoint / Resume（断点续跑）
- ADR-0024 Condition / Branching（条件分支）

每个都是新关注点。如果继续走子类化，Router 层级会继续膨胀：
```
Router → HealthAwareRouter → ScoreRouter → MetricsRouter → RetryRouter → CheckpointRouter → ...
```

**4. Runtime Contract §8 已为退出画好路径**

V0.9.6 落地时，Runtime Contract §2 原则 F 和 §8 已明确：

> **V2.0 退出路径**：MetricsRouter 应被 BridgeResult raw extension 或 **ExecutionPipeline Decorator** 替代。

> **MetricsRouter is transitional**（ChatGPT Q5 措辞调整）
> **Server metrics extraction should migrate into future runtime infrastructure**
> 不写死具体实现（Pipeline / Middleware / Interceptor / Execution Runtime 都是候选）

V1.0.1 是退出 MetricsRouter 临时层的最佳窗口。

### 现状代码示例

```python
# router/metrics_router.py（V0.9.6 临时层）
class MetricsRouter(ScoreRouter):
    def execute(self, task: Task) -> Result:
        provider = self.route(task)  # ← 复制父类 route 逻辑
        if provider is None: ...
        if self.quota and self.quota.exhausted(...): ...
        bridge = provider.select_bridge(task)
        br = bridge.run(task)
        # V0.9.6 新增：插入 metrics 提取
        server_metrics = MetricsExtractor.extract(provider.name, bridge, br)
        if br.success and self.quota: ...
        return Result(...)
```

30+ 行代码 90% 重复父类 `execute()`，只为插入 1 行 metrics 提取。

## 目标

**核心目标**：让 Router 重新变瘦，只负责 `route(task)`。所有执行期关注点（metrics / health / future retry / future checkpoint）走 ExecutionPipeline 装饰器链。

**具体目标**：

1. **Router 瘦身**：`Router.execute()` 维持薄薄一层（route → bridge → Result），不再被各子类覆盖
2. **Pipeline 接管**：所有"装饰 execute()"的逻辑搬到 `planner/pipeline.py` 的 Stage 里
3. **MetricsRouter 退出路径**：V0.9.6 临时层功能由 `MetricsStage` 替代（V1.0.1 仍保留旧类做兼容，V1.0.3 删除）
4. **新关注点友好**：未来 Retry / Checkpoint 都是新 Stage，零 Router 修改
5. **Core Freeze 继续**：`core/` + `router/router.py` + `providers/` 不动
6. **Runtime Contract 6 原则不动**：ExecutionEvent 不可变 / Source of Truth / Read-Only Projection 全部保留

## 决策

### 决策 1：ExecutionPipeline 整体架构

**新增** `planner/pipeline.py`，定义 `ExecutionContext` + `ExecutionStage` + `ExecutionPipeline`：

```python
# planner/pipeline.py（V1.0.1 新增）
from __future__ import annotations
from typing import Protocol, runtime_checkable
from core.result import Result
from core.task import Task
from core.provider import Provider
from core.bridge import BridgeResult


@dataclass
class ExecutionContext:
    """Pipeline 透传的不可变上下文。

    Attributes:
        task: 当前 Task
        provider: route() 选中的 Provider（None 表示 routing 失败）
        bridge_result: bridge.run() 返回的 BridgeResult（None 表示尚未执行）
        result: 最终返回的 Result（Pipeline 末端组装）
    """
    task: Task
    provider: Provider | None = None
    bridge_result: BridgeResult | None = None
    result: Result | None = None

    def with_provider(self, provider: Provider | None) -> "ExecutionContext":
        """返回新 context（不可变原则）。"""
        return ExecutionContext(
            task=self.task,
            provider=provider,
            bridge_result=self.bridge_result,
            result=self.result,
        )

    def with_bridge_result(self, br: BridgeResult) -> "ExecutionContext":
        return ExecutionContext(
            task=self.task,
            provider=self.provider,
            bridge_result=br,
            result=self.result,
        )

    def with_result(self, result: Result) -> "ExecutionContext":
        return ExecutionContext(
            task=self.task,
            provider=self.provider,
            bridge_result=self.bridge_result,
            result=result,
        )


@runtime_checkable
class ExecutionStage(Protocol):
    """Pipeline Stage 接口（V1.0.1 协议）。

    每个 Stage 负责一个关注点：
    - MetricsStage：提取 server_metrics
    - RetryStage（V1.0.2）：失败重试
    - CheckpointStage（V1.0.3）：断点续跑
    - ...

    Stage 通过修改 context（with_xxx）或短路（提前返回 Result）来介入执行链。
    Stage 不修改 ExecutionEvent（Runtime Contract 原则 B）。
    """

    @property
    def name(self) -> str: ...

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        """处理 context，返回新 context（不可变）。

        短路语义（V1.0.1 决策点 3）：
        - 正常：返回新 context，Pipeline 继续
        - 短路：ctx.result is not None，Pipeline 跳过 bridge.run
        """
        ...


class ExecutionPipeline:
    """执行管道：Stage 列表 + Router + Base Executor。

    执行流程（V1.0.1）：
        1. Pipeline.run(task) 入口
        2. for stage in pre_bridge_stages: ctx = stage(ctx)
        3. if ctx.result is not None: return ctx.result  # 短路
        4. provider = ctx.provider (来自 RouteStage)
        5. br = provider.select_bridge(task).run(task)  # Base Execute
        6. ctx = ctx.with_bridge_result(br)
        7. for stage in post_bridge_stages: ctx = stage(ctx)
        8. return PipelineExecutor.assemble_result(ctx)  # 组装 Result

    Stage 注册顺序：
        pre_bridge:  [RouteStage]
        post_bridge: [MetricsStage, HealthStage, ...]（按关注点顺序）

    V1.0.1 默认 pipeline:
        pre_bridge:  [RouteStage()]
        post_bridge: [MetricsStage()]

    V1.0.2+ 增加:
        post_bridge: [MetricsStage(), RetryStage()]
        等
    """

    def __init__(
        self,
        router: Router,
        pre_bridge_stages: list[ExecutionStage] = None,
        post_bridge_stages: list[ExecutionStage] = None,
        quota: QuotaManager | None = None,
    ):
        self.router = router
        self.pre_bridge_stages = pre_bridge_stages or []
        self.post_bridge_stages = post_bridge_stages or []
        self.quota = quota

    def run(self, task: Task) -> Result:
        """执行 task 经过所有 Stage，返回 Result。"""
        ctx = ExecutionContext(task=task)

        # 1. Pre-bridge stages
        for stage in self.pre_bridge_stages:
            ctx = stage(ctx)
            if ctx.result is not None:
                return ctx.result  # 短路

        # 2. Base execute（route + bridge.run）
        ctx = self._base_execute(ctx)
        if ctx.result is not None:
            return ctx.result  # 短路（routing/quota 失败）

        # 3. Post-bridge stages
        for stage in self.post_bridge_stages:
            ctx = stage(ctx)
            # post-bridge Stage 不短路（必须有最终 result）

        # 4. 组装 Result
        return PipelineExecutor.assemble_result(ctx)

    def _base_execute(self, ctx: ExecutionContext) -> ExecutionContext:
        """薄薄一层：route → quota check → bridge.run。

        这一层取代 Router.execute() 的主链路。
        不再被子类覆盖，所有装饰逻辑在 Stage 里。
        """
        provider = self.router.route(ctx.task)

        if provider is None:
            return ctx.with_result(Result(
                provider="none",
                status="failed",
                output="",
                error=f"No available provider for capabilities: {ctx.task.capabilities}",
                metadata={"capabilities": ctx.task.capabilities, "task_id": ctx.task.task_id},
            ))

        if self.quota and self.quota.exhausted(provider.name):
            return ctx.with_result(Result(
                provider=provider.name,
                status="failed",
                output="",
                error=f"Quota exhausted for {provider.name}",
                metadata={"capabilities": ctx.task.capabilities, "task_id": ctx.task.task_id,
                           "fallback_reason": "quota_exhausted"},
            ))

        bridge = provider.select_bridge(ctx.task)
        br = bridge.run(ctx.task)

        if br.success and self.quota:
            self.quota.ensure(provider.name, provider.metadata.quota_total,
                             provider.metadata.quota_type)
            self.quota.consume(provider.name, task_id=ctx.task.task_id)

        return ctx.with_provider(provider).with_bridge_result(br)
```

**架构图**：

```
Task
  │
  ▼
ExecutionPipeline.run(task)
  │
  ├── pre_bridge_stages
  │     │
  │     ▼
  │   RouteStage (V1.0.1)
  │     │
  │     ▼ (ctx.provider set)
  │
  ├── _base_execute (Pipeline 内部)
  │     │
  │     ├─ Router.route(task) → Provider
  │     ├─ Quota check
  │     ├─ provider.select_bridge(task).run(task) → BridgeResult
  │     │
  │     ▼ (ctx.bridge_result set)
  │
  ├── post_bridge_stages
  │     │
  │     ├─ MetricsStage (V1.0.1)
  │     │     │
  │     │     └─ ctx.result.metadata["server_metrics"] = extract(...)
  │     │
  │     ├─ RetryStage (V1.0.2+)
  │     ├─ CheckpointStage (V1.0.3+)
  │     │
  │     ▼
  │
  └── assemble_result(ctx) → Result
```

**关键不变量**：
- `ExecutionContext` 不可变（每次 with_xxx 返回新对象）
- Stage 不修改 ExecutionEvent（Runtime Contract 原则 B）
- Stage 不接触 SQLite / EventBus（除非显式订阅）
- Pipeline 失败必须返回 Result（不抛异常）

### 决策 2：MetricsStage 取代 MetricsRouter.execute() 装饰

**新增** `planner/pipeline.py` 内的 `MetricsStage`：

```python
class MetricsStage:
    """Post-bridge Stage：从 BridgeResult 提取 server_metrics。

    取代 MetricsRouter.execute() 中的内联 metrics 提取逻辑。

    API Stability: Experimental
    """

    def __init__(self, extractor: MetricsExtractor | None = None):
        self.extractor = extractor or MetricsExtractor()
        self.name = "metrics"

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        """从 ctx.bridge_result 提取 server_metrics 并写入 ctx.result.metadata。

        关键约束：
        - 提取失败 → server_metrics = {}（不影响主链路）
        - 不修改 ctx.bridge_result（不可变）
        - 不抛异常
        """
        if ctx.bridge_result is None or ctx.result is not None:
            return ctx  # 短路或无 br，不处理

        provider_name = ctx.provider.name if ctx.provider else "unknown"
        bridge = ctx.provider.select_bridge(ctx.task) if ctx.provider else None

        try:
            server_metrics = self.extractor.extract(
                provider_name, bridge, ctx.bridge_result
            )
        except Exception as e:
            # 提取失败不抛异常，log 后继续
            server_metrics = {}

        # 更新 result.metadata
        new_metadata = dict(ctx.result.metadata)
        new_metadata["server_metrics"] = server_metrics
        new_result = Result(
            provider=ctx.result.provider,
            status=ctx.result.status,
            output=ctx.result.output,
            error=ctx.result.error,
            artifacts=ctx.result.artifacts,
            metadata=new_metadata,
        )
        return ctx.with_result(new_result)
```

**为什么 Stage 而不是 metrics-aware Result wrapper？**
- Stage 顺序可配（metrics → retry → checkpoint 可以自由组合）
- Stage 失败隔离（一个 Stage 失败不影响其他）
- Stage 易于测试（独立单元）
- 与 V1.0.2 Retry / V1.0.3 Checkpoint 天然契合

### 决策 3：RouteStage 取代 Router.execute() 路由

**新增** `planner/pipeline.py` 内的 `RouteStage`：

```python
class RouteStage:
    """Pre-bridge Stage：调用 router.route() 选 Provider。

    让 Router 只负责 route()，不负责 execute() 装饰。
    """

    def __init__(self, router: Router):
        self.router = router
        self.name = "route"

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        """调用 router.route() 设置 ctx.provider。

        路由失败（provider is None）时短路：
        - ctx.result = failed Result
        - Pipeline 跳过 base_execute
        """
        provider = self.router.route(ctx.task)
        if provider is None:
            return ctx.with_result(Result(
                provider="none",
                status="failed",
                output="",
                error=f"No available provider for capabilities: {ctx.task.capabilities}",
                metadata={"capabilities": ctx.task.capabilities, "task_id": ctx.task.task_id},
            )).with_provider(None)
        return ctx.with_provider(provider)
```

**关键设计**：
- Router 退化为只读 `route()`（V0.8 ScoreRouter 已有，V0.9.7 不动）
- `Router.execute()` 仍然存在但**不再被 Pipeline 调用**（向后兼容）
- Pipeline 用 `RouteStage` 调 `Router.route()`

### 决策 4：Core Freeze 兼容性

**V1.0.1 决策**：
- ❌ **不修改** `router/router.py`（Router.execute() 仍存在，但 Pipeline 不用）
- ❌ **不修改** `router/health_router.py`（HealthAwareRouter 仍可用，但 Pipeline 不用）
- ❌ **不修改** `router/score_router.py`（ScoreRouter 仍可用）
- ⚠️ **`router/metrics_router.py` 保留但标记 Deprecated**
- ✅ **新增** `planner/pipeline.py`（Pipeline 主体）
- ✅ **新增** `planner/stages/metrics_stage.py`（V1.0.1 唯一新 Stage）

**为什么不删除 MetricsRouter？**
- V1.0.1 过渡期，外部代码可能仍引用
- 标记 `@deprecated` 提示迁移到 Pipeline
- V1.0.3（Checkpoint 落地后）正式删除

**Router.execute() 仍然有用**：
- 单一 Bridge 调用场景（不需要 Pipeline 装饰）
- 测试代码简化（不需要构造完整 Pipeline）
- 向后兼容层

### 决策 5：PipelineExecutor.assemble_result

**新增** `planner/pipeline.py` 内的 `PipelineExecutor`：

```python
class PipelineExecutor:
    """Pipeline 内部 helper：组装最终 Result。

    V1.0.1 简化版：直接从 ctx 派生 Result。
    V1.0.2+ 扩展：增加 Result 中间件（post-processing）。
    """

    @staticmethod
    def assemble_result(ctx: ExecutionContext) -> Result:
        """从 ctx 组装最终 Result。"""
        if ctx.result is not None:
            # 已有 result（短路或 Stage 已组装）
            return ctx.result

        if ctx.bridge_result is None or ctx.provider is None:
            # 不应到达这里，但防御性
            return Result(
                provider="unknown",
                status="failed",
                output="",
                error="Pipeline internal error: missing bridge_result",
                metadata={"task_id": ctx.task.task_id},
            )

        br = ctx.bridge_result
        return Result(
            provider=ctx.provider.name,
            status="success" if br.success else "failed",
            output=br.output,
            error=br.error,
            artifacts=br.artifacts,
            metadata={
                "duration_ms": br.duration_ms,
                "capabilities": ctx.task.capabilities,
                "task_id": ctx.task.task_id,
                "bridge": type(ctx.provider.select_bridge(ctx.task)).__name__,
                "quota_remaining": ctx.provider.quota_left(),
            },
        )
```

**为什么不在 Stage 中组装 Result？**
- 单一职责：Stage 只装饰，组装由 Executor 负责
- 短路语义清晰：短路时 Stage 已设 ctx.result，正常时由 Executor 统一组装
- 易于测试：Stage 测装饰逻辑，Executor 测组装逻辑

### 决策 6：默认 Pipeline 工厂

**新增** `planner/pipeline.py` 内的 `default_pipeline()`：

```python
def default_pipeline(
    router: Router,
    quota: QuotaManager | None = None,
    include_metrics: bool = True,
) -> ExecutionPipeline:
    """构造 V1.0.1 默认 Pipeline。

    默认 Stages:
        pre_bridge:  [RouteStage(router)]
        post_bridge: [MetricsStage()]  (if include_metrics)

    Args:
        router: Router 实例（通常是 ScoreRouter）
        quota: QuotaManager（可选）
        include_metrics: 是否包含 MetricsStage（默认 True）

    Returns:
        ExecutionPipeline 实例
    """
    pre_bridge = [RouteStage(router)]
    post_bridge = []
    if include_metrics:
        post_bridge.append(MetricsStage())
    return ExecutionPipeline(
        router=router,
        pre_bridge_stages=pre_bridge,
        post_bridge_stages=post_bridge,
        quota=quota,
    )
```

**为什么是工厂函数而不是 Pipeline 类的默认值？**
- V1.0.2+ Stage 列表会变化
- 不同场景（CLI / Server / Test）需要不同 Pipeline
- 工厂函数让 Stage 选择显式可见

### 决策 7：PlanExecutor 迁移到 Pipeline

**修改** `planner/executor.py`：

```python
# 修改前（V0.9.7）
class PlanExecutor:
    def __init__(self, ...):
        self.router = ScoreRouter(...)
        # 直接用 router.execute()

# 修改后（V1.0.1）
class PlanExecutor:
    def __init__(self, ...):
        self.router = ScoreRouter(...)
        self.pipeline = default_pipeline(self.router, quota=...)

    def _execute_step(self, task):
        return self.pipeline.run(task)  # 不再 router.execute(task)
```

**修改原则**：
- PlanExecutor 内部用 `self.pipeline.run(task)` 替代 `self.router.execute(task)`
- 对外 API 不变（仍返回 Result）
- ExecutionEvent 仍由 PlanExecutor 发射（EventBus 订阅不变）

### 决策 8：Runtime Contract 影响

**Runtime Contract §2 原则 F（V0.9.6）**：

原文：
> V2.0 退出路径：MetricsRouter 应被 BridgeResult raw extension 或 ExecutionPipeline Decorator 替代。

**V1.0.1 落地**：
- 选择"ExecutionPipeline Decorator"路径
- 原则 F 强化为："V1.0.1 起，MetricsRouter 是 Deprecated，新代码必须用 MetricsStage"
- Runtime Contract §8 更新："V1.0.1 起，MetricsRouter 临时层由 MetricsStage 取代"

**Runtime Contract §8 V0.9.6 临时层**：

原文：
> 不写死具体实现（Pipeline / Middleware / Interceptor / Execution Runtime 都是候选）
> V2.0 退出时由具体 V1.0 实施决定

**V1.0.1 决定**：
- 选择 "ExecutionPipeline as Decorator / Middleware"（Pipeline / Middleware 之一）
- 不选择 BridgeResult raw extension（更侵入，需要改 BridgeResult）
- 不选择 Execution Runtime（V1.0.x 太重）

**Runtime Contract §9 版本演进表新增**：

```
| V1.0.1 | 引入 ExecutionPipeline as Decorator；MetricsRouter 标记 Deprecated（V1.0.3 删除） |
```

### 决策 9：API Stability 策略

**API Stability 分级**：
- `ExecutionContext` — Experimental（V1.0.1 → V1.1 可能重构字段）
- `ExecutionStage` Protocol — Experimental（V1.0.2+ 可能增加新方法）
- `ExecutionPipeline` — Experimental
- `MetricsStage` — Experimental
- `RouteStage` — Experimental
- `default_pipeline()` 工厂 — Experimental

**兼容性**：
- V1.0.1 之前用 `Router.execute()` 的代码**仍然工作**（Router.execute() 保留）
- V1.0.1 推荐用 `ExecutionPipeline.run()` 替代
- V1.0.3 之前 `MetricsRouter` 仍可用（标记 Deprecated）
- V1.0.3 删除 `MetricsRouter`

**为什么不一步删除 MetricsRouter？**
- V1.0.1 引入 Pipeline 已经是大改动
- 立即删除 MetricsRouter 会让升级路径断裂
- V1.0.3 删除给用户 2 个小版本（V1.0.1 / V1.0.2）迁移窗口

### 决策 10：测试策略

**测试覆盖**：
- `test_pipeline.py`（新增）— ExecutionPipeline 基础
  - 空 pipeline（只有 RouteStage）正常执行
  - MetricsStage 提取 server_metrics
  - MetricsStage 失败不抛异常
  - 短路语义（RouteStage routing 失败）
  - Stage 顺序正确
  - ExecutionContext 不可变
- `test_metrics_stage.py`（新增）— MetricsStage 独立测试
  - 提取成功路径
  - 提取失败路径
  - 提取异常路径
  - 多种 provider 适配
- `test_executor_pipeline_integration.py`（新增）— PlanExecutor 集成
  - 旧 router.execute() 与新 pipeline.run() 行为一致
  - ExecutionEvent 流不变
  - EventBus 订阅不变
- `test_metrics_router_deprecated.py`（新增）— 验证旧 MetricsRouter 仍可用
  - 旧 import 不报错
  - 旧 router.execute() 行为不变
  - 标记 deprecation warning
- `test_existing.py`（全部）— 行为不变验证

**目标测试基线**：V0.9.7 (123 passed) → V1.0.1 (140+ passed)。

**关键回归测试**：
- `test_cli_plan.py` / `test_cli_plan_json.py` / `test_cli_exec_history.py` — version 1.0.0 → 1.0.1
- `test_statistics.py` / `test_cli_stats.py` — 不变（V0.9.7 已 FINAL）
- 全部 `test_*event*.py` / `test_*metrics*.py` — 不变（Runtime Contract 6 原则不变）

## 架构

### 执行前（V0.9.7 收官后）

```
Task
  │
  ▼
PlanExecutor
  │
  ▼
MetricsRouter.execute(task)        ← 30+ 行主链路 + metrics 提取
  │
  ├─ ScoreRouter.route(task)        ← route 选择
  ├─ HealthAwareRouter.route()      ← health 过滤
  ├─ Router.route()                  ← 基础 route
  │
  ├─ provider.select_bridge(task)   ← 选 bridge
  ├─ bridge.run(task)                ← 执行
  ├─ MetricsExtractor.extract()     ← 提取 metrics
  │
  ▼
Result (with server_metrics)
```

**问题**：Router 层级 4 层，每层复制主链路。

### 执行后（V1.0.1）

```
Task
  │
  ▼
PlanExecutor
  │
  ▼
ExecutionPipeline.run(task)
  │
  ├─ pre_bridge_stages:
  │     └─ RouteStage
  │           └─ Router.route(task) → Provider
  │
  ├─ _base_execute (Pipeline 内部薄层)
  │     ├─ Quota check
  │     ├─ provider.select_bridge(task).run(task)
  │     └─ ctx.with_bridge_result(br)
  │
  ├─ post_bridge_stages:
  │     └─ MetricsStage
  │           └─ extract server_metrics → ctx.result.metadata
  │
  ▼
PipelineExecutor.assemble_result(ctx) → Result
```

**收益**：
- Router 只剩 `route()`，不复制主链路
- 新关注点（V1.0.2 Retry / V1.0.3 Checkpoint）零 Router 修改
- Stage 单元测试独立，可组合

### MetricsRouter 退出路径时间线

```
V0.9.6  MetricsRouter 引入（临时层）
V0.9.7  Runtime Contract 明确 V2.0 退出路径
V1.0.0  ARCHITECTURE.md 启动基线
V1.0.1  ExecutionPipeline 引入 + MetricsStage 替代 MetricsRouter 装饰
        MetricsRouter 标记 @deprecated（仍可用）
V1.0.2  RetryStage 引入（Pipeline 第二个 Stage）
        MetricsRouter 仍 Deprecated
V1.0.3  CheckpointStage 引入
        MetricsRouter 删除
V1.0.4  ConditionStage 引入
V1.x    OmniRouteProvider 融合（ADR-0025）
```

## 范围

### 只做

1. `planner/pipeline.py`（新增）— `ExecutionContext` + `ExecutionStage` Protocol + `ExecutionPipeline` + `RouteStage` + `MetricsStage` + `PipelineExecutor` + `default_pipeline()` 工厂
2. `planner/stages/`（新增目录）— Stage 子包（V1.0.1 暂只放 metrics，V1.0.2+ 增加 retry / checkpoint）
3. `planner/executor.py`（修改）— PlanExecutor 内部用 Pipeline 替代 router.execute()
4. `router/metrics_router.py`（修改）— 加 `@deprecated` 标记
5. `docs/runtime-contract.md`（修改）— §2 原则 F + §8 V0.9.6 临时层 + §9 版本演进表
6. 完整测试

### 不做（V1.0.2+ / V1.0.3+ 推迟）

- ❌ V1.0.2 RetryStage（独立 ADR-0022）
- ❌ V1.0.3 CheckpointStage（独立 ADR-0023）
- ❌ V1.0.4 ConditionStage（独立 ADR-0024）
- ❌ 删除 MetricsRouter（V1.0.3 才删）
- ❌ 修改 `core/` + `router/router.py` + `providers/`
- ❌ 修改 `ExecutionEvent` / `EventBus` / `ExecutionMetrics`（Runtime Contract 6 原则不变）
- ❌ 修改 `metadata.schema_version`（仍为 "1"）
- ❌ 修改 `Router.execute()`（保留向后兼容，Pipeline 不调它）
- ❌ 异步 Pipeline（V1.0.x 同步，V2.0+ 评估）
- ❌ Pipeline 持久化（V1.0.x Pipeline 内存态，V1.0.3 Checkpoint 评估）

## 测试策略

### 单元测试

- `test_pipeline.py`（新增，约 12 tests）
  - `test_pipeline_runs_route_stage_first`
  - `test_pipeline_runs_metrics_stage_after_bridge`
  - `test_pipeline_short_circuit_on_route_failure`
  - `test_pipeline_assembles_result_when_no_post_bridge_stages`
  - `test_pipeline_handles_empty_post_bridge_stages`
  - `test_execution_context_is_immutable`
  - `test_execution_context_with_provider_returns_new_instance`
  - `test_default_pipeline_factory_includes_metrics_by_default`
  - `test_default_pipeline_factory_can_exclude_metrics`
  - `test_pipeline_does_not_call_router_execute`
  - `test_pipeline_returns_result_on_all_failure_paths`
  - `test_pipeline_quota_check_before_bridge_run`

- `test_metrics_stage.py`（新增，约 8 tests）
  - `test_metrics_stage_extracts_server_metrics`
  - `test_metrics_stage_handles_missing_bridge_result`
  - `test_metrics_stage_handles_already_set_result`
  - `test_metrics_stage_returns_empty_dict_on_extraction_failure`
  - `test_metrics_stage_does_not_modify_bridge_result`
  - `test_metrics_stage_does_not_throw_on_extraction_exception`
  - `test_metrics_stage_preserves_existing_metadata`
  - `test_metrics_stage_uses_provider_name_in_extraction`

- `test_route_stage.py`（新增，约 6 tests）
  - `test_route_stage_calls_router_route`
  - `test_route_stage_sets_provider_on_context`
  - `test_route_stage_short_circuits_when_no_provider`
  - `test_route_stage_preserves_existing_context_fields`
  - `test_route_stage_does_not_modify_task`
  - `test_route_stage_handles_router_route_exception`

- `test_executor_pipeline_integration.py`（新增，约 6 tests）
  - `test_plan_executor_uses_pipeline_internally`
  - `test_plan_executor_pipeline_run_matches_old_router_execute`
  - `test_plan_executor_emits_same_execution_events`
  - `test_plan_executor_pipeline_run_returns_same_result_shape`
  - `test_plan_executor_pipeline_run_with_metrics_stage`
  - `test_plan_executor_pipeline_run_without_metrics_stage`

- `test_metrics_router_deprecated.py`（新增，约 4 tests）
  - `test_metrics_router_import_emits_deprecation_warning`
  - `test_metrics_router_execute_still_works`
  - `test_metrics_router_execute_returns_same_result_as_pipeline`
  - `test_metrics_router_class_docstring_marks_deprecated`

### 回归测试

- `test_cli_plan.py`（更新 version 1.0.0 → 1.0.1）
- `test_cli_plan_json.py`（更新 version 1.0.0 → 1.0.1）
- `test_cli_exec_history.py`（更新 version 1.0.0 → 1.0.1）
- 全部 `test_*event*.py` / `test_*metrics*.py` / `test_*statistics*.py` — 不变（行为兼容）

**目标基线**：V0.9.7 (123 passed) → V1.0.1 (140+ passed)。

## 兼容性

### 向后兼容

- `Router.execute()` 保留（不再被 Pipeline 调用，但外部代码可用）
- `MetricsRouter` 保留（标记 `@deprecated`，V1.0.3 删除）
- `HealthAwareRouter` / `ScoreRouter` 保留（V1.0.1 仍用 ScoreRouter 做 Router 注入）
- `PlanExecutor.__init__` 签名不变
- `PlanExecutor._execute_step` 返回值不变
- ExecutionEvent 流不变
- EventBus 订阅不变
- metadata.schema_version 维持 "1"

### 行为兼容

- 旧 `Router.execute(task)` 与新 `ExecutionPipeline.run(task)` 返回等价 Result
- `server_metrics` 提取逻辑等价（MetricsStage 与 MetricsRouter.extract 一致）
- Quota 扣减时机不变（bridge.run 成功后扣减）
- Result.metadata 字段不变（除 server_metrics 顺序可能略有差异）

### 升级路径

外部代码迁移：
```python
# 修改前（V0.9.7）
from router.metrics_router import MetricsRouter
router = MetricsRouter(registry, quota)
result = router.execute(task)

# 修改后（V1.0.1+）
from planner.pipeline import default_pipeline
from router.score_router import ScoreRouter
router = ScoreRouter(registry, quota, health)
pipeline = default_pipeline(router, quota=quota)
result = pipeline.run(task)
```

V1.0.1 → V1.0.2 → V1.0.3 三个版本都是过渡期，V1.0.3 删除 MetricsRouter。

## 风险

| 风险 | 缓解 |
|------|------|
| Pipeline.run 与 Router.execute 行为不一致 | 集成测试 `test_plan_executor_pipeline_run_matches_old_router_execute` |
| Stage 顺序影响结果 | 单元测试覆盖每种顺序组合；文档明确 default 顺序 |
| ExecutionContext 不可变性被破坏 | 单元测试 `test_execution_context_is_immutable`；Stage 实现 review |
| MetricsStage 失败影响主链路 | 提取失败返回 `{}`，不抛异常（沿用 V0.9.6 MetricsRouter 策略） |
| PlanExecutor 集成破坏现有测试 | 集成测试覆盖；ExecutionEvent 流不变 |
| MetricsRouter Deprecated 警告太多 | 一次性 deprecation，不在测试中加 filter；用户可控 |
| 旧代码未迁移到 Pipeline | V1.0.3 删除前给 2 个版本过渡期；提供迁移文档 |
| Stage 性能（每步新建 context） | V1.0.x Stage 数量 <5，性能影响可忽略；V1.1+ 评估对象池 |

## 确认问题（发 ChatGPT 审核）

1. **ExecutionContext 不可变性**：`with_xxx` 每次返回新对象。是否合理？还是应该用 mutable context + Stage 内部复制？（V1.0.1 倾向不可变：与 ExecutionEvent 不可变原则一致）
2. **Stage 接口设计**：`__call__(ctx) -> ctx` Protocol 模式。是否合理？还是应该用抽象基类（ABC）？还是显式 `process(ctx)` 方法？
3. **短路语义**：`ctx.result is not None` 表示短路。是否合理？还是应该用显式 `StopPipeline` exception？或 `ctx.short_circuit: bool` 字段？
4. **MetricsStage 取代 MetricsRouter**：V1.0.1 引入 Stage + 标记 MetricsRouter Deprecated，V1.0.3 删除。是否合理？还是应该 V1.0.1 直接删除 MetricsRouter（一步到位）？
5. **Router.execute() 保留**：`Router.execute()` 不被 Pipeline 调用但仍存在。是否合理？还是应该 V1.0.1 直接删除 `Router.execute()`（强制迁移）？
6. **Pipeline 默认同步**：`ExecutionPipeline.run(task)` 同步执行。V1.0.x 不做异步。是否合理？还是应该 V1.0.1 引入 `async def run`？
7. **Pipeline 不持久化**：Pipeline 状态在内存，Checkpoint 持久化推迟到 V1.0.3。是否合理？还是应该 V1.0.1 Pipeline 一起做持久化？
8. **Scope 克制**：V1.0.1 只做 Pipeline + MetricsStage，不做 Retry / Checkpoint（推迟到 V1.0.2 / V1.0.3）。是否合理？是否应该 V1.0.1 一次性把 V1.0.x 的 4 个 Stage 都做掉？

## 后续路线

```
V1.0.0  ARCHITECTURE.md Accepted (10.0/10 FINAL)          ← 已完成
  ↓
V1.0.1  ExecutionPipeline as Decorator / Middleware (本 ADR)  ← Proposed
        - 引入 ExecutionContext / ExecutionStage Protocol
        - 引入 RouteStage + MetricsStage
        - MetricsRouter 标记 @deprecated
  ↓
V1.0.2  ADR-0022 Retry Policy
        - 新增 RetryStage（pipeline.post_bridge_stages）
        - 退避策略 / 最大重试 / 错误分类
  ↓
V1.0.3  ADR-0023 Checkpoint / Resume
        - 新增 CheckpointStage
        - 持久化 Pipeline 状态（plan_id / step_id / ctx 快照）
        - 删除 MetricsRouter
  ↓
V1.0.4  ADR-0024 Condition / Branching
        - 新增 ConditionStage
        - 基于 ExecutionEvent 的条件分支
  ↓
V1.x    ADR-0025 OmniRouteProvider 融合
        - 通过 APIBridge + Pipeline 调用 OmniRoute
        - 复用 V0.9.6 MetricsExtractor 模式提取 server_metrics
```

## Runtime Contract 同步更新

V1.0.1 通过后，需更新 `docs/runtime-contract.md`：

1. **§2 原则 F 强化**：
   - 原文："V2.0 退出路径：MetricsRouter 应被 BridgeResult raw extension 或 ExecutionPipeline Decorator 替代"
   - 改为："V1.0.1 起，MetricsRouter 标记 @deprecated，由 ExecutionPipeline 的 MetricsStage 替代。V1.0.3 删除。"

2. **§8 V0.9.6 临时层**：
   - 原文："不写死具体实现"
   - 改为："V1.0.1 选择 ExecutionPipeline as Decorator / Middleware 路径。MetricsRouter 临时层由 MetricsStage 取代。"

3. **§9 版本演进表新增**：
   ```
   | V1.0.1 | 引入 ExecutionPipeline as Decorator；MetricsRouter Deprecated |
   | V1.0.2 | 引入 RetryStage |
   | V1.0.3 | 引入 CheckpointStage；删除 MetricsRouter |
   | V1.0.4 | 引入 ConditionStage |
   ```

4. **§8 末尾新增**：
   ```
   V1.0.1 新增 ExecutionPipeline 抽象（见 ADR-0021）：
   - ExecutionContext 不可变
   - Stage 通过 Protocol 接口介入
   - 短路语义：ctx.result is not None
   - Pipeline.run(task) 是 V1.0+ 标准执行入口
   ```

## 不在 V1.0.1 范围

以下内容**不**在本 ADR 范围（避免范围蔓延）：

- ❌ Retry / Backoff / Circuit Breaker（V1.0.2 ADR-0022）
- ❌ Checkpoint / Resume / Saga（V1.0.3 ADR-0023）
- ❌ Condition / Branching / DAG（V1.0.4 ADR-0024）
- ❌ OmniRouteProvider 融合（V1.x ADR-0025）
- ❌ 异步 Pipeline（V2.0+ 评估）
- ❌ Pipeline 持久化（V1.0.3 Checkpoint 评估）
- ❌ Pipeline 监控（V1.x）
- ❌ Pipeline 调试工具（V1.x）
- ❌ 动态 Stage 加载（V1.x）

---

> V1.0.1 ADR-0021 Proposed（待 ChatGPT 外部审核）。
> 核心目标：让 Router 重新变瘦，所有执行期关注点走 ExecutionPipeline 装饰器链。
> 关键约束：Core Freeze 继续 + Runtime Contract 6 原则不变 + metadata.schema_version 维持 "1"。
> 落地后：V0.9.6 MetricsRouter 临时层正式进入退出路径（V1.0.3 删除）。
