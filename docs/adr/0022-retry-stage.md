# ADR-0022: V1.0.2 — RetryStage (失败重试)

- **状态**: Accepted（ChatGPT 外部审核 9.9/10 FINAL APPROVED）
- **日期**: 2026-07-18
- **里程碑**: V1.0.2
- **关联**: ADR-0021（V1.0.1 ExecutionPipeline，10.0/10 FINAL APPROVED）、[Runtime Contract](../runtime-contract.md) §2 原则 F + §6 Capability Routing、[ARCHITECTURE.md §2.3](../ARCHITECTURE.md) V1.0 路线
- **API Stability**: Experimental
- **前序基线**: V1.0.1 ExecutionPipeline（670e84b，10.0/10 FINAL APPROVED）
- **本版审核**: [ADR-0022 ChatGPT Review](../reviews/0022-adr-chatgpt-review.md) — 9.9/10 FINAL APPROVED
- **ChatGPT V1.0.1 强烈建议**: "下一步直接进入 ADR-0022 RetryStage"，"不要碰 Pipeline"，"Retry 只是 class RetryStage: 即可"

## 背景

V1.0.1 ExecutionPipeline 引入后（[ADR-0021](0021-execution-pipeline.md)，10.0/10 FINAL APPROVED），所有执行期关注点都通过 `ExecutionStage` 装饰器链介入。Pipeline 已足够稳定，不需要修改。

V1.0.2 是 Pipeline 之后第一个真正利用扩展性的 ADR：**RetryStage** 接管失败重试。

### 当前痛点

**V1.0.1 Pipeline 失败处理**：

```python
# planner/pipeline.py _base_execute
br = ctx.bridge.run(ctx.task)
# 失败：直接返回 br（status="failed"）
# 不重试
```

当前 Pipeline **没有重试**。一旦 bridge.run() 返回 success=False，立即组装 failed Result 返回。

**现实场景需要重试**：
- LLM API 限流（429 Too Many Requests）
- 网络瞬时失败（502/503/504）
- Bridge 临时不可用
- Provider 临时超载

这些场景下"立即失败"体验差，应该自动重试。

### V0.9.6 已有 Quota 拦截，但无重试

`pipeline._base_execute` 已经有 `quota.exhausted` 拦截（quota 耗尽立即返回 failed），但**不重试**。

### Runtime Contract §2 原则 F + §6 已有空间

- 原则 F（V0.9.6）：ExecutionMetrics vs server_metrics 分层
- §6 Capability Routing：Task → Capability → Provider

重试策略应该：
- 在 Pipeline 层介入（post-bridge Stage 位置）
- 不影响 routing 决策（原则 F）
- 不破坏 Capability Routing（§6）

## 目标

**核心目标**：通过 `RetryStage` 接管失败重试，让 Pipeline 在特定错误下自动重试。

**具体目标**：

1. **Pipeline 扩展性验证**：证明 V1.0.1 Pipeline 设计正确，新关注点零 Pipeline 修改
2. **RetryStage 可配置**：
   - 最大重试次数（默认 3）
   - 退避策略（exponential / linear / immediate / fixed）
   - 错误分类（retryable / non-retryable）
3. **不影响 Routing**：Retry 失败重试不改 Provider（ChatGPT Q1 强调）
4. **不影响 MetricsStage**：重试结果仍带 server_metrics
5. **Runtime Contract 6 原则不变**
6. **Core Freeze 继续**：`core/` + `router/router.py` + `providers/` 不动
7. **Metadata schema 不变**：`metadata.schema_version` 维持 "1"
8. **新 ExecutionContext 字段**：`retry_count` / `max_retries` / `last_error` / `last_bridge_result`（Stage 共享）

## 决策

### 决策 1：RetryStage 架构（不修改 Pipeline）

按 ChatGPT V1.0.1 强烈建议：

> "下一步直接进入 ADR-0022 RetryStage。"
> "不要碰 Pipeline。Pipeline 现在已经足够稳定。"
> "Retry 应该只是：class RetryStage: 即可。"

**新增** `planner/stages/retry_stage.py`：

```python
# planner/stages/retry_stage.py（V1.0.2 新增）
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from planner.pipeline import ExecutionContext, ExecutionStage

logger = logging.getLogger(__name__)


class RetryStage:
    """Post-bridge Stage：对失败 BridgeResult 实施重试。

    介入位置：pipeline.post_bridge_stages[0]（MetricsStage 之前）
    重试语义：
    - BridgeResult.success = True -> 不重试，直接 pass
    - BridgeResult.success = False -> 分类重试
      - retryable 错误 -> 计算 backoff -> 重新执行 ctx.bridge.run() -> 更新 ctx.bridge_result
      - non-retryable 错误 -> 不重试，让 MetricsStage / PipelineExecutor 处理
    - 重试次数耗尽 -> 不重试，ctx.bridge_result 保留最后一次失败结果

    关键不变量：
    - 不修改 Provider（ChatGPT Q1：重试不改 routing）
    - 不修改 ExecutionEvent（Runtime Contract 原则 B）
    - 不接触 SQLite / EventBus（Stage SHOULD be Side-Effect Minimal）
    - 不修改 ctx.result（MetricsStage 负责）
    - 不抛异常

    API Stability: Experimental
    """

    def __init__(
        self,
        max_retries: int = 3,
        backoff: str = "exponential",  # "exponential" | "linear" | "fixed" | "immediate"
        initial_delay_ms: int = 100,
        max_delay_ms: int = 5000,
        is_retryable: Optional[Callable[[BridgeResult], bool]] = None,
    ):
        self.max_retries = max_retries
        self.backoff = backoff
        self.initial_delay_ms = initial_delay_ms
        self.max_delay_ms = max_delay_ms
        # 默认：所有错误都可重试
        self.is_retryable = is_retryable or self._default_retryable
        self._name = "retry"

    @property
    def name(self) -> str:
        return self._name

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        """如果 bridge_result 失败且可重试，循环重试直到成功或耗尽。

        Returns:
            新的 ExecutionContext（更新 retry_count + last_bridge_result + bridge_result）
            如果不需要重试或耗尽，返回 ctx 不变。
        """
        if ctx.stop or ctx.bridge_result is None or ctx.bridge is None:
            return ctx  # 短路 / 无 bridge

        if ctx.bridge_result.success:
            return ctx  # 成功，不重试

        # 失败，分类
        if not self.is_retryable(ctx.bridge_result):
            logger.info(
                "RetryStage: non-retryable error, skip. error=%s",
                ctx.bridge_result.error,
            )
            return ctx

        # 循环重试
        for attempt in range(1, self.max_retries + 1):
            delay_ms = self._compute_delay(attempt)
            logger.info(
                "RetryStage: retrying attempt=%d delay_ms=%d error=%s",
                attempt, delay_ms, ctx.bridge_result.error,
            )
            time.sleep(delay_ms / 1000.0)
            br = ctx.bridge.run(ctx.task)
            ctx = ctx.with_bridge_result(br)
            if br.success:
                logger.info("RetryStage: success after %d retries", attempt)
                break
            if not self.is_retryable(br):
                logger.info("RetryStage: non-retryable after retry %d", attempt)
                break

        return ctx

    def _compute_delay(self, attempt: int) -> int:
        """计算第 attempt 次重试的延迟（毫秒）。"""
        if self.backoff == "immediate":
            return 0
        if self.backoff == "fixed":
            return self.initial_delay_ms
        if self.backoff == "linear":
            return min(self.initial_delay_ms * attempt, self.max_delay_ms)
        # exponential (default)
        delay = self.initial_delay_ms * (2 ** (attempt - 1))
        return min(delay, self.max_delay_ms)

    @staticmethod
    def _default_retryable(br: BridgeResult) -> bool:
        """默认 retryable 策略：所有失败都可重试。

        用户可自定义 is_retryable 来限制：
        - 只重试 5xx / 429
        - 不重试 4xx (除 429)
        - 不重试 timeout
        """
        return not br.success
```

**Pipeline 接入**（V1.0.2 修改）：

```python
# planner/pipeline.py
# default_pipeline() 增加可选 include_retry 参数
def default_pipeline(
    router: Router,
    quota: Any = None,
    include_metrics: bool = True,
    include_retry: bool = False,  # V1.0.2 新增
) -> ExecutionPipeline:
    pre_bridge = [RouteStage(router)]
    post_bridge = []
    if include_retry:
        # RetryStage 在前（先重试，再提取 metrics）
        post_bridge.append(RetryStage())
    if include_metrics:
        post_bridge.append(MetricsStage())
    return ExecutionPipeline(
        router=router,
        pre_bridge_stages=pre_bridge,
        post_bridge_stages=post_bridge,
        quota=quota,
    )
```

**Stage 顺序**（关键）：

```
post_bridge_stages = [RetryStage, MetricsStage]
                       ↑         ↑
                       先重试      重试后提取 metrics
```

### 决策 2：ExecutionContext 不增加 retry 字段（V1.0.2 克制）

V1.0.2 决策：ExecutionContext **不增加** retry 字段。

**为什么？**
- ChatGPT V1.0.1 Q3 已建议"为 Retry/Condition 留状态空间"
- 但 V1.0.2 是"克制扩展"，避免一次大改
- 重试状态在 RetryStage 内部用局部变量追踪
- 用户想看重试信息：靠日志（V1.0+ 评估加 `ctx.retry_count`）

**未来扩展**（V1.0+ 评估）：

```python
# V1.0.2+ 评估加 ctx.retry_count 等字段
ctx.retry_count: int = 0
ctx.max_retries: int = 3
ctx.last_error: str | None = None
ctx.last_bridge_result: BridgeResult | None = None
```

**采纳原因**：当前 V1.0.2 验证 Pipeline 扩展性，retry 状态可放 Stage 局部。如果 V1.0.3 CheckpointStage 需要持久化 retry 状态，再加字段。

### 决策 3：错误分类（is_retryable）

V1.0.2 决策：**默认"安全可重试"**（ChatGPT 唯一建议采纳），允许用户自定义 `is_retryable` 函数。

**默认策略**（ChatGPT Q3 采纳，9.9/10）：

```python
# 默认安全重试策略：只重试网络/超时/限流/5xx
SAFE_RETRY_PATTERNS = {
    "TimeoutError",      # 网络超时
    "ConnectionError",   # 连接失败
    "RateLimitError",    # 限流 (429)
    "ServiceUnavailableError",  # 5xx
    "InternalServerError",      # 5xx
    "BadGatewayError",          # 5xx
    "GatewayTimeoutError",      # 5xx
}

def _default_retryable(br: BridgeResult) -> bool:
    """默认安全重试：仅网络/超时/限流/5xx 错误可重试。
    
    LLM Provider 常见永久错误 (401/403/404/quota exhausted 等) 不重试：
    - 401 Unauthorized: api key 无效
    - 403 Forbidden: 权限不足
    - 404 Not Found: model 不存在
    - 400 Bad Request: 参数错误
    - quota exhausted: 配额耗尽
    - validation: 输入验证失败
    
    这些错误重试只是浪费时间，失败原因不会因重试恢复。
    
    用户可自定义 is_retryable 完全覆盖默认行为：
        RetryStage(is_retryable=lambda br: True)  # 重试所有错误
    """
    if br.success:
        return False
    # 检查 error type
    error_type = br.error_type or ""  # BridgeResult.error_type 字段
    if error_type in SAFE_RETRY_PATTERNS:
        return True
    # 检查 status_code (raw 字段)
    status_code = br.raw.get("status_code") if br.raw else None
    if status_code is not None:
        # 5xx 全部重试, 429 限流重试, 其他 4xx 不重试
        if status_code >= 500 or status_code == 429:
            return True
        return False
    # 无明确错误信息时, 不重试（保守）
    return False
```

**用户自定义示例**（V1.0.2 文档）：

```python
# 场景 1: 重试所有错误（不推荐生产环境）
RetryStage(is_retryable=lambda br: not br.success)

# 场景 2: 只重试 5xx + 429
def only_5xx_and_429(br: BridgeResult) -> bool:
    status = br.raw.get("status_code") if br.raw else None
    if status is None:
        return False  # 保守：明确无 status_code 不重试
    return status >= 500 or status == 429

# 场景 3: 自定义错误类型
def custom_retry(br: BridgeResult) -> bool:
    if br.success: return False
    if "timeout" in (br.error or "").lower(): return True
    if "rate limit" in (br.error or "").lower(): return True
    return False
```

**为什么默认是函数而不是枚举？**
- 用户可能想基于错误内容、错误码、provider 等多种条件判断
- 函数最灵活
- 默认实现采用 ChatGPT 建议的"安全可重试"策略

**ChatGPT 评价**：
> "我建议默认策略改成：Timeout / ConnectionError / 5xx / RateLimit → Retry"
> "Validation / Permission / Authentication / 4xx → No Retry"
> "LLM Provider 很多失败根本不会因为 Retry 而恢复（401/403/404/invalid api key/invalid model/quota exhausted）"

### 决策 4：退避策略

V1.0.2 决策：**4 种退避策略**（字符串枚举）。

| 策略 | 公式 | 默认延迟 |
|------|------|----------|
| `immediate` | 0 | 0ms |
| `fixed` | initial_delay_ms | 100ms |
| `linear` | initial_delay_ms * attempt | 100ms, 200ms, 300ms, ... |
| `exponential` (default) | initial_delay_ms * 2^(attempt-1) | 100ms, 200ms, 400ms, 800ms, ... |

**最大延迟保护**：`max_delay_ms`（默认 5000ms）防止 exponential 无限增长。

**为什么不支持自定义退避函数？**
- V1.0.2 保持简单
- V1.0+ 评估加 `compute_delay: Callable[[int], int]` 参数

### 决策 5：Core Freeze 兼容性

V1.0.2 决策：

- ❌ **不修改** `core/` + `router/router.py` + `providers/`
- ❌ **不修改** `planner/pipeline.py` 主体（仅修改 `default_pipeline()` 工厂）
- ✅ **新增** `planner/stages/retry_stage.py`（V1.0.2 第一个非 metrics Stage）
- ✅ **修改** `planner/pipeline.py` 的 `default_pipeline()` 工厂（增加 `include_retry` 参数）
- ✅ **修改** `planner/executor.py`（默认 `include_retry=True` for production，但 V1.0.2 测试期默认 False）

**为什么不默认开启 RetryStage？**
- V1.0.2 验证 Pipeline 扩展性，retry 是可选关注点
- 默认 False 避免破坏现有测试
- 用户显式开启：`pipeline = default_pipeline(router, quota, include_retry=True)`
- V1.0.3+ 评估：是否改默认

### 决策 6：MetricsStage 行为不变

V1.0.2 决策：**MetricsStage 不知道 RetryStage 存在**。

- MetricsStage 照常从 `ctx.bridge_result` 提取 server_metrics
- 重试后的最终 bridge_result 自然带最终 server_metrics
- MetricsStage 不需要修改

**关键验证**：test_metrics_stage.py 仍 100% pass（V0.9.6 已有测试 + V1.0.1 39 测试）。

### 决策 7：API Stability 策略

| API | Stability |
|-----|-----------|
| `RetryStage` | Experimental |
| `RetryStage.__init__` 参数 | Experimental |
| `is_retryable` 函数参数 | Experimental |
| `default_pipeline(include_retry=...)` 参数 | Experimental |
| `planner/stages/` 子包 | Experimental |
| 4 种退避策略名称 | Stable（API 字符串） |

### 决策 8：测试策略

**新增测试** `tests/test_retry_stage.py`（约 15 tests）：

- `TestRetryStageBasics`（5 tests）：
  - `test_retry_on_failure_eventually_succeeds`
  - `test_retry_exhausts_after_max_retries`
  - `test_retry_skips_on_success`
  - `test_retry_skips_on_non_retryable`
  - `test_retry_does_not_throw_on_bridge_exception`
- `TestRetryStageBackoff`（4 tests）：
  - `test_immediate_backoff`
  - `test_fixed_backoff`
  - `test_linear_backoff`
  - `test_exponential_backoff`
- `TestRetryStageCustomIsRetryable`（3 tests）：
  - `test_custom_retryable_function`
  - `test_retryable_5xx_only`
  - `test_non_retryable_4xx`
- `TestRetryStageIntegration`（3 tests）：
  - `test_retry_stage_before_metrics_stage`
  - `test_retry_does_not_call_router_execute`
  - `test_retry_does_not_modify_provider`

**回归测试**：

- 全部 V1.0.1 测试 0 回归
- 全部 V0.9.x 测试 0 回归
- 全部 V0.9.7 metrics / statistics 测试 0 回归

**目标基线**：V1.0.1 (507 passed) → V1.0.2 (525+ passed)。

### 决策 9：Runtime Contract 影响

V1.0.2 决策：

- §2 原则 F：**不变**（retry 仍不影响 routing）
- §6 Capability Routing：**不变**（重试不改 capability 解析）
- §8 V0.9.6 临时层：**不变**（仍由 MetricsStage 替代 MetricsRouter）
- §9 版本演进表：新增 V1.0.2 行

**新增 Runtime Contract 原则**（V1.0.2 评估）：

> "Stage SHOULD be Side-Effect Minimal"（V1.0+ 评估，V1.0.1 ChatGPT 建议）
> "RetryStage MUST NOT change routing decision"（V1.0.2 新增）

**未采纳**（V1.0+ 评估）：

- "Stage Exception Policy"（Skip/Abort/Retry）：V1.0.2 决策，RetryStage 失败不重试就 pass，不 Skip/Abort
- "Pipeline Idempotence"：V1.0.1 ChatGPT 建议，V1.0.2 评估

### 决策 10：Stage 顺序验证（Pipeline 扩展性证据）

V1.0.2 关键验证：Stage 顺序对结果的影响。

**默认顺序**：
```
post_bridge_stages = [RetryStage, MetricsStage]
```

**反向顺序**（不应该用）：
```
post_bridge_stages = [MetricsStage, RetryStage]  # metrics 在重试前
```

**两种顺序的影响**：
- `[RetryStage, MetricsStage]`：先重试，metrics 反映重试后的最终 bridge_result
- `[MetricsStage, RetryStage]`：先提取 metrics（基于首次失败结果），然后重试（metrics 不更新）

**采纳默认**：`[RetryStage, MetricsStage]`（重试后 metrics 反映最终结果）。

**Pipeline 提供的灵活性**：
- 用户可自定义 stage 列表
- 不强制顺序
- 仅 default_pipeline() 给出推荐顺序

## 架构

### RetryStage 接入前后对比

**接入前**（V1.0.1）：
```
Task
  │
  ▼
ExecutionPipeline.run(task)
  │
  ├── pre_bridge: [RouteStage]
  │     └─ router.route() → ctx.provider + ctx.bridge
  │
  ├── _base_execute
  │     └─ ctx.bridge.run() → ctx.bridge_result  (失败直接走完)
  │
  ├── post_bridge: [MetricsStage]
  │     └─ extract server_metrics
  │
  ▼
Result (failed if bridge failed)
```

**接入后**（V1.0.2）：
```
Task
  │
  ▼
ExecutionPipeline.run(task)
  │
  ├── pre_bridge: [RouteStage]
  │     └─ router.route() → ctx.provider + ctx.bridge
  │
  ├── _base_execute
  │     └─ ctx.bridge.run() → ctx.bridge_result
  │
  ├── post_bridge: [RetryStage, MetricsStage]
  │     ├─ RetryStage: 如果 failed + retryable -> 重试 -> 更新 bridge_result
  │     └─ MetricsStage: 从最终 bridge_result 提取 server_metrics
  │
  ▼
Result (success if any retry succeeded, else failed)
```

### Pipeline 不变证据

`planner/pipeline.py` V1.0.2 修改：
- `ExecutionContext`：0 修改
- `ExecutionStage` Protocol：0 修改
- `RouteStage`：0 修改
- `MetricsStage`：0 修改
- `PipelineExecutor`：0 修改
- `ExecutionPipeline.run`：0 修改（只接 post_bridge_stages 列表）
- `default_pipeline()`：**1 个参数**（`include_retry`），**0 行逻辑修改**

**Pipeline 真正只负责"调度"，Stage 各自负责"装饰"**。

## 范围

### 只做

1. `planner/stages/__init__.py`（新增）— 子包入口
2. `planner/stages/retry_stage.py`（新增）— RetryStage 实现
3. `planner/pipeline.py`（修改）— `default_pipeline()` 增加 `include_retry` 参数
4. `planner/executor.py`（修改）— 增加 `include_retry` 参数透传
5. `tests/test_retry_stage.py`（新增）— 15 tests
6. `docs/runtime-contract.md`（修改）— §9 版本演进表 + 新增 RetryStage 原则
7. ChatGPT 审核 + 调整 + Accepted

### 不做（V1.0.2 克制）

- ❌ ExecutionContext 增加 retry 字段（V1.0+ 评估）
- ❌ 修改 Pipeline 主体（仅 default_pipeline 工厂）
- ❌ 修改 MetricsStage / RouteStage
- ❌ 异步重试（V2.0+ 评估）
- ❌ 重试持久化（V1.0.3 CheckpointStage 评估）
- ❌ 自定义 backoff 函数（V1.0+ 评估）
- ❌ 删除 MetricsRouter（V1.0.3 才删）
- ❌ 修改 core/ + router/router.py + providers/
- ❌ 修改 metadata.schema_version（仍 "1"）

## 测试策略

### 单元测试

- `test_retry_stage.py`（新增，15 tests）
  - `TestRetryStageBasics`（5）
  - `TestRetryStageBackoff`（4）
  - `TestRetryStageCustomIsRetryable`（3）
  - `TestRetryStageIntegration`（3）

### 回归测试

- 全部 V1.0.1 测试 0 回归
- 全部 V0.9.x 测试 0 回归
- 全部 V0.9.7 metrics / statistics 测试 0 回归

**目标基线**：V1.0.1 (507 passed) → V1.0.2 (525+ passed)。

## 兼容性

### 向后兼容

- `RetryStage` 是新的，用户不传就**不会**启用重试
- `default_pipeline(include_retry=False)` 默认行为不变
- `planner/pipeline.py` 主体 0 行为变化
- `ExecutionContext` 0 字段变化
- `ExecutionStage` Protocol 0 变化
- `Router.execute()` 仍保留向后兼容

### 行为兼容

- 不启用 RetryStage 时，V1.0.2 行为完全等同 V1.0.1
- 启用 RetryStage 时，failure → retry → success 路径增加
- 重试不改变 provider（ChatGPT Q1 强烈强调）
- 重试不改变 server_metrics 提取逻辑（MetricsStage 不变）

### 升级路径

用户想开启重试：
```python
# 修改前（V1.0.1）
from planner.pipeline import default_pipeline
pipeline = default_pipeline(router, quota=quota)
# 默认无重试

# 修改后（V1.0.2+，用户主动开启）
from planner.pipeline import default_pipeline
pipeline = default_pipeline(router, quota=quota, include_retry=True)
# RetryStage 启用

# 或自定义 RetryStage
from planner.stages.retry_stage import RetryStage
pipeline = ExecutionPipeline(
    router=router,
    pre_bridge_stages=[RouteStage(router)],
    post_bridge_stages=[
        RetryStage(max_retries=5, backoff="exponential"),
        MetricsStage(),
    ],
    quota=quota,
)
```

## 风险

| 风险 | 缓解 |
|------|------|
| RetryStage 顺序错误影响 metrics | `test_retry_stage_before_metrics_stage` 验证；default_pipeline 给出推荐顺序 |
| 重试次数过多导致 LLM 成本翻倍 | `max_retries` 默认 3；`max_delay_ms` 限制 exponential 增长 |
| 重试错误分类不当（重试 401） | 默认所有错误可重试；用户传 `is_retryable` 自定义；文档示例 |
| 重试过程中抛异常 | RetryStage 内部 try/except；失败 → ctx 不变（不传播） |
| RetryStage 改动影响其他 Stage | RetryStage 不修改 ctx.result / ctx.provider / ctx.bridge；只更新 ctx.bridge_result |
| Pipeline 主体被误改 | ADR-0022 决策 1 明确"不修改 Pipeline 主体"；reviewer 检查 |
| MetricsStage 行为变化 | test_metrics_stage 0 回归验证 |
| PlanExecutor 默认行为变化 | `include_retry=False` 默认，V1.0.2 不破坏现有 PlanExecutor 用户 |

## 确认问题（发 ChatGPT 审核）

1. **RetryStage 不改 Pipeline 主体**：仅 default_pipeline() 加 1 个参数。是否合理？还是 V1.0.2 应该改 Pipeline 增强通用性？
2. **ExecutionContext 不增加 retry 字段**：重试状态在 Stage 内部追踪。是否合理？还是 V1.0.2 应该加 ctx.retry_count？
3. **错误分类用函数 is_retryable**：默认所有错误可重试，用户自定义。是否合理？还是应该用枚举（RETRYABLE / NON_RETRYABLE / ALL）？
4. **退避策略用字符串枚举**：4 种策略（immediate/fixed/linear/exponential）。是否合理？还是应该用 Callable 接受自定义函数？
5. **默认关闭重试**：V1.0.2 include_retry=False 默认。是否合理？还是应该默认开启？
6. **默认 max_retries=3**：3 次重试。是否合理？还是 5 次？
7. **退避 initial_delay_ms=100 / max_delay_ms=5000**：默认 100ms 初始 + 5s 上限。是否合理？还是应该更长？
8. **Scope 克制**：V1.0.2 只做 RetryStage + Pipeline 工厂加 1 个参数。是否合理？是否应该同时加 ExecutionContext 字段 / Pipeline 增强 / 错误分类枚举？

## 后续路线

```
V1.0.0  ARCHITECTURE.md Accepted (10.0/10 FINAL)          ← 已完成
V1.0.1  ExecutionPipeline (ADR-0021)                     ← 10.0/10 FINAL APPROVED (670e84b)
  ↓
V1.0.2  ADR-0022 RetryStage (本 ADR)                      ← Proposed
        - RetryStage 加进 pipeline.post_bridge_stages
        - 4 种退避策略 + 自定义 is_retryable
        - 不改 Pipeline 主体
  ↓
V1.0.3  ADR-0023 Checkpoint / Resume
        - 新增 CheckpointStage
        - 持久化 Pipeline 状态
        - 删除 MetricsRouter
  ↓
V1.0.4  ADR-0024 Condition / Branching
        - 新增 ConditionStage
        - 基于 ExecutionEvent 的条件分支
  ↓
V1.x    ADR-0025 OmniRouteProvider 融合
        - 通过 APIBridge + Pipeline 调用 OmniRoute
```

## Runtime Contract 同步更新

V1.0.2 通过后，需更新 `docs/runtime-contract.md`：

1. **§9 版本演进表新增**：
   ```
   | V1.0.2 | 引入 RetryStage（ADR-0022）；Pipeline 扩展性验证 |
   ```

2. **新增 RetryStage 原则**（V1.0.2 评估）：
   ```
   V1.0.2 RetryStage:
   - RetryStage MUST NOT change routing decision
   - RetryStage SHOULD classify errors (is_retryable)
   - RetryStage default is_retryable: only network/timeout/5xx/rate_limit
     - 不重试: 4xx (除 429), validation, permission, authentication
     - 用户可自定义 is_retryable 完全覆盖
   - RetryStage MUST NOT modify Provider / Bridge
   - RetryStage failure: pass (不重试/不抛异常)
   - RetryStage SHOULD only retry idempotent bridge executions (ChatGPT 建议)
   ```

3. **Stage 顺序约定**：
   ```
   V1.0+ 推荐 post_bridge_stages 顺序:
   [RetryStage, MetricsStage]
   - 先重试（失败可重试）
   - 再 metrics（提取最终 server_metrics）
   ```

## 不在 V1.0.2 范围

- ❌ ExecutionContext 加 retry 字段（V1.0+ 评估）
- ❌ 自定义 backoff 函数（V1.0+ 评估）
- ❌ 异步重试（V2.0+）
- ❌ 重试持久化（V1.0.3 CheckpointStage 评估）
- ❌ 错误分类枚举（V1.0.2 用函数）
- ❌ 删除 MetricsRouter（V1.0.3）
- ❌ Stage Exception Policy（V1.0+ 评估）
- ❌ Pipeline Idempotence 验证（V1.0+ 评估）
- ❌ Unknown Stage 处理（V1.0+ 评估）

---

> V1.0.2 ADR-0022 Accepted（ChatGPT 外部审核 9.9/10 FINAL APPROVED）。
> 采纳 1 项关键调整：
> 1. Q3 默认 is_retryable：从"所有失败可重试"改为"仅安全可重试"（ChatGPT 唯一扣分点）
>
> 进入实施阶段（V1.0.2 实施循环启动）。
