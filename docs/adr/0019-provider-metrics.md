# ADR-0019: V0.9.6 — Provider Metrics（Token / Cost 自动采集）

- **状态**: Proposed
- **日期**: 2026-07-17
- **里程碑**: V0.9.6
- **关联**: ADR-0008（Core Freeze）、ADR-0017（Execution Event）、ADR-0018（SQLiteExecutionStore + Storage is Disposable）
- **API Stability**: Experimental
- **前序审核**: [V0.9.5 代码 ChatGPT Review](../reviews/V0.9.5-code-chatgpt-review.md) — 10.0/10 APPROVED

## 背景

V0.9.4 引入 ExecutionEvent 模型，V0.9.5 引入 SQLiteExecutionStore 持久化。观察链已闭环：

```
ExecutionEvent → TraceCollector (Memory)
              → SQLiteExecutionStore (Persistent)
              → Future Metrics ← V0.9.6
              → Future UI
              → Future Remote Sync
```

但当前 `ExecutionMetrics` 只有 `latency_ms` 被填充（V0.9.4），`token_in / token_out / cost_usd / retry_count` 全部为 0。原因：

1. **Provider 不返回 metrics**：Provider 是纯 Adapter，不接触 EventBus（ADR-0017 原则）
2. **Bridge 捕获了数据但被丢弃**：APIBridge 把完整 HTTP response body（含 OpenAI `usage`）存到 `BridgeResult.raw`，但 `Router.execute`（冻结）在 `BridgeResult → Result` 转换时丢弃 `br.raw`
3. **没有提取器**：即使拿到 `br.raw`，也没有代码从 HTTP body 中提取 `usage.prompt_tokens / completion_tokens`

### 核心矛盾

```
[Provider]     [Bridge]                [Router]                 [PlanExecutor]
   │              │                       │                         │
   │ 不返回        │ BridgeResult.raw      │ Router.execute():       │ 拿到 Result
   │ metrics      │ 携带 HTTP body        │ 丢弃 br.raw ❌          │ (无 raw)
   ↓              ↓                       ↓                         ↓
  无数据      data in raw but unused   Result.metadata             无法提取
                                      无 server_metrics
```

## 目标

把 Provider 调用后的 token / cost 数据采集到 ExecutionEvent，让：
- `provider_finished` event 的 `data` 携带 `server_metrics`
- `Step.execution_metrics` 填充 `token_in / token_out / cost_usd`
- `Plan.aggregate_metrics` 能聚合全 Plan 的 token / cost
- SQLiteExecutionStore 自动持久化（已有 `data` 列支持 JSON）

**约束**：
- ❌ 不改 core/（provider.py / bridge.py / result.py）
- ❌ 不改 providers/（Provider 保持纯 Adapter）
- ❌ 不改 router/router.py（Core Freeze）
- ✅ 可新增 router/ 下新文件（子类化）
- ✅ 可改 planner/（Experimental）
- ✅ 可新增 planner/metrics/ 模块

## 决策

### 决策 1：MetricsRouter 子类化（路径 A）

**新增** `router/metrics_router.py`：

```python
# router/metrics_router.py（新增，不修改 router/router.py）
from router.router import Router
from core.result import Result
from core.task import Task
from planner.metrics.extractors import MetricsExtractor

class MetricsRouter(Router):
    """Router 子类：在 execute() 中额外提取 server_metrics。

    不覆盖 route()（路由逻辑不变），只覆盖 execute() 加 metadata 字段。
    符合 ADR-0008 Core Freeze 精神：扩展 metadata 不算修改路由逻辑。
    """

    def execute(self, task: Task) -> Result:
        # 复用父类路由逻辑
        provider = self.route(task)
        if provider is None:
            return Result(provider="none", status="failed", output="", error="no provider")

        bridge = provider.select_bridge(task)
        br = bridge.run(task)

        # V0.9.6 新增：从 br.raw 提取 server_metrics
        server_metrics = MetricsExtractor.extract(provider.name, bridge, br)

        result = Result(
            provider=provider.name,
            status="success" if br.success else "failed",
            output=br.output,
            error=br.error,
            artifacts=br.artifacts,
            metadata={
                "duration_ms": br.duration_ms,
                "capabilities": task.capabilities,
                "task_id": task.task_id,
                "bridge": type(bridge).__name__,
                "quota_remaining": provider.quota_left(),
                "server_metrics": server_metrics,  # ← V0.9.6 新增
            },
        )
        # Quota 扣减（复用父类逻辑或复制）
        ...
        return result
```

**为什么不直接改 Router.execute？**
- Router 冻结（ADR-0008）
- 子类化是 OOP 标准扩展模式，不改父类代码
- `route()` 没动，路由评分逻辑完全不变

**Core Freeze 边界论证**：
- ADR-0008 说"修改 router/ 路由逻辑 ❌"
- MetricsRouter 没改 `route()`，只覆盖 `execute()` 在 `Result.metadata` 加了一个新键
- "扩展 metadata" ≠ "修改路由逻辑"
- 路由逻辑 = 选哪个 Provider；metadata 扩展 = 执行后附加信息
- **结论**：子类化扩展 metadata 不违反 Core Freeze

### 决策 2：MetricsExtractor 按 Provider 分发

**新增** `planner/metrics/extractors.py`：

```python
# planner/metrics/extractors.py（新增）
class MetricsExtractor:
    """按 provider name 分发提取 server_metrics。

    返回 dict（符合 ADR-0018 原则 B：JSON 可序列化）：
        {
            "token_in": int,
            "token_out": int,
            "token_total": int,
            "cost_usd": float,
            "model": str,
        }
    无数据时返回空 dict {}。
    """

    @staticmethod
    def extract(provider_name: str, bridge, br) -> dict:
        if not br.success or br.raw is None:
            return {}
        # 按 provider name 分发
        handler = _HANDLERS.get(provider_name, _extract_nothing)
        return handler(bridge, br)

def _extract_openai(bridge, br) -> dict:
    """从 OpenAI HTTP response body 提取 usage。"""
    try:
        data = json.loads(br.raw) if isinstance(br.raw, str) else br.raw
        usage = data.get("usage", {})
        model = data.get("model", "")
        token_in = usage.get("prompt_tokens", 0)
        token_out = usage.get("completion_tokens", 0)
        cost = Pricing.compute(model, token_in, token_out)
        return {
            "token_in": token_in,
            "token_out": token_out,
            "token_total": usage.get("total_tokens", token_in + token_out),
            "cost_usd": cost,
            "model": model,
        }
    except (json.JSONDecodeError, TypeError, AttributeError):
        return {}

_HANDLERS = {
    "openai_api": _extract_openai,
    "openai_compatible": _extract_openai,
    # gemini_cli / qoder / stub / demo / fake_browser / web_ai:
    #   无 token 数据源，返回空 dict
}
```

**为什么返回 dict 而不是 dataclass？**
- 符合 ADR-0018 原则 B（JSON 可序列化）
- 符合 ADR-0018 原则 C（Event Query 统一，data 是 free-form）
- 未来新增字段（如 `reasoning_tokens`）不用改类

### 决策 3：Pricing 价格表

**新增** `planner/metrics/pricing.py`：

```python
# planner/metrics/pricing.py（新增）
# OpenAI 官方定价（USD per 1K tokens）
# 来源：https://openai.com/pricing（手动维护，价格变动时更新）

_PRICING = {
    # (input_per_1k, output_per_1k)
    "gpt-4":           (0.03, 0.06),
    "gpt-4-turbo":     (0.01, 0.03),
    "gpt-4o":          (0.0025, 0.01),
    "gpt-4o-mini":     (0.00015, 0.0006),
    "gpt-3.5-turbo":   (0.0005, 0.0015),
    # 兜底
    "_default":        (0.01, 0.03),
}

class Pricing:
    @staticmethod
    def compute(model: str, token_in: int, token_out: int) -> float:
        prices = _PRICING.get(model, _PRICING["_default"])
        return round(token_in / 1000 * prices[0] + token_out / 1000 * prices[1], 6)
```

**为什么手动维护价格表？**
- OpenAI API 不返回单价（只返回 token 数）
- 价格表是静态配置，不频繁变动
- 未来可扩展为从配置文件 / 环境变量加载

**价格表准确性**：
- V0.9.6 是"近似成本估算"，不是"精确计费"
- 用户应以 Provider 官方账单为准
- ADR 明确：cost_usd 是估算值，不作为计费依据

### 决策 4：PlanExecutor 改造

**修改** `planner/executor.py`（行 142-152）：

```python
# 现状（V0.9.4）：
self._emit_event(
    "provider_finished",
    plan_id=plan.plan_id,
    step_id=step.step_id,
    provider=result.provider,
    latency_ms=provider_latency_ms,
    data={"status": result.status},
)
step.execution_metrics = ExecutionMetrics(
    latency_ms=provider_latency_ms,
    # token_in/token_out/cost_usd 全为 0
)

# V0.9.6 改为：
server_metrics = result.metadata.get("server_metrics", {})
self._emit_event(
    "provider_finished",
    plan_id=plan.plan_id,
    step_id=step.step_id,
    provider=result.provider,
    latency_ms=provider_latency_ms,
    data={
        "status": result.status,
        "server_metrics": server_metrics,  # ← 新增
    },
)
step.execution_metrics = ExecutionMetrics(
    latency_ms=provider_latency_ms,
    token_in=server_metrics.get("token_in", 0),
    token_out=server_metrics.get("token_out", 0),
    cost_usd=server_metrics.get("cost_usd", 0.0),
)
```

**为什么从 `result.metadata` 取而不是直接调 Extractor？**
- PlanExecutor 不应该知道 Provider 细节（关注点分离）
- MetricsRouter 负责提取，PlanExecutor 只负责消费
- 符合 "Provider 不接触 EventBus" 原则的延伸：PlanExecutor 也不接触 Bridge

### 决策 5：CLI 注入 MetricsRouter

**修改** `cli/plan.py`（注入点）：

```python
# 现状（V0.9.5）：
from router.score_router import ScoreRouter
router = ScoreRouter(registry, ...)

# V0.9.6 改为：
from router.metrics_router import MetricsRouter
router = MetricsRouter(registry, ...)
# MetricsRouter 继承 ScoreRouter 的 route() 逻辑
```

**为什么不改 cli/ask.py？**
- `ai-hub ask` 是单次调用，不需要 metrics 持久化
- `ai-hub plan` 才有 PlanExecutor + EventBus
- 保持 `ask` 的简单性

### 决策 6：不支持 token 采集的 Provider

| Provider | Bridge | token 采集 | 原因 |
|----------|--------|-----------|------|
| openai_api | APIBridge | ✅ 支持 | `BridgeResult.raw` 含 HTTP body（usage） |
| openai_compatible | APIBridge | ✅ 支持 | 同上 |
| gemini_cli | CLIBridge | ❌ 不支持 | 命令用 `-o text`，无 token 输出 |
| qoder | CLIBridge | ❌ 不支持 | CLI 输出格式未明 |
| stub | CLIBridge | ❌ N/A | 本地 fake runtime |
| demo | FakeBridge | ❌ N/A | 无 API 调用 |
| fake_browser | BrowserBridge | ❌ N/A | 浏览器自动化 |
| web_ai | BrowserBridge | ❌ N/A | 浏览器自动化 |

**V0.9.6 决策**：接受 gemini_cli / qoder 的 token 为 0。latency_ms 仍正常采集。

**为什么不改 gemini_cli 用 `-o json`？**
- 改 providers/ 违反 Core Freeze
- gemini_cli 的 `-o json` 输出格式需调研
- V0.9.6 范围克制：先支持有数据的 Provider，未来 Core Freeze 解冻再补

### 决策 7：server_metrics 不入 schema_version

**Postel's Law 延续**（ADR-0017 决策 10 + ADR-0018 决策 10）：
- `server_metrics` 是 `ExecutionEvent.data` 的新子键
- `data` 是 free-form dict，加子键不需要升级 schema_version
- 老 Consumer 读不到 `server_metrics` 静默忽略
- 新 Consumer 读 `data.get("server_metrics", {})` 容错

**`metadata.schema_version` 维持 "1"**。

### 决策 8：CLI 查看 Metrics

**新增命令**（或扩展现有命令）：

```
ai-hub exec-history --plan <plan_id>          # 已有，timeline 现在显示 token/cost
ai-hub exec-history --plan <plan_id> --json   # 已有，JSON 现在包含 server_metrics
```

**timeline 输出增强**（`cli/history.py` 的 `_describe_event`）：

```
12:01:00.123  0.1s  provider_finished  (openai_api, 500ms, success, in=120 out=45 cost=$0.0021)
```

**不新增独立 metrics 命令**：
- V0.9.6 范围克制
- V0.9.7 Statistics 时再做 `ai-hub stats` 命令

### 决策 9：Core Freeze 维持

- core/ + router/router.py + providers/ 0 修改
- V0.9.6 全部新增 / 修改在 `router/metrics_router.py`（新）+ `planner/metrics/`（新）+ `planner/executor.py`（改）+ `cli/plan.py`（改）+ `cli/history.py`（改）
- MetricsRouter 是 router/ 下的新文件，不修改 router.py

## 架构

```
┌──────────────────────────────────────────────────────┐
│ PlanExecutor (planner/executor.py)                   │
│                                                      │
│   router = MetricsRouter(...)  ← V0.9.6 注入          │
│   result = router.execute(task)                      │
│                                                      │
│   server_metrics = result.metadata["server_metrics"] │
│                                                      │
│   emit("provider_finished", data={                   │
│       "status": ...,                                 │
│       "server_metrics": server_metrics  ← V0.9.6     │
│   })                                                 │
│                                                      │
│   step.execution_metrics = ExecutionMetrics(         │
│       latency_ms=...,                                │
│       token_in=server_metrics["token_in"],  ← V0.9.6 │
│       token_out=server_metrics["token_out"], ← V0.9.6│
│       cost_usd=server_metrics["cost_usd"],  ← V0.9.6 │
│   )                                                  │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
              ┌─────────────────────┐
              │ MetricsRouter       │ (router/metrics_router.py 新增)
              │   .route()  [继承]  │ ← 路由逻辑不变
              │   .execute() [覆盖] │ ← 加 server_metrics 到 metadata
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │ MetricsExtractor    │ (planner/metrics/extractors.py 新增)
              │   .extract(name,    │
              │      bridge, br)    │
              │   按 provider 分发   │
              └──────────┬──────────┘
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
   ┌─────────────────┐      ┌─────────────────┐
   │ _extract_openai │      │ _extract_nothing│
   │ (openai_api,    │      │ (gemini_cli,    │
   │  openai_compat) │      │  qoder, stub,   │
   │                 │      │  demo, ...)     │
   │ json.loads(raw) │      │                 │
   │ → usage → token │      │ return {}       │
   │ → Pricing.compute│      │                 │
   └────────┬────────┘      └─────────────────┘
            │
            ▼
   ┌─────────────────┐
   │ Pricing         │ (planner/metrics/pricing.py 新增)
   │   .compute(model,│
   │    token_in,     │
   │    token_out)    │
   │ → cost_usd       │
   └─────────────────┘
```

## 范围

### 只做

1. `router/metrics_router.py`（新增）— MetricsRouter（Router 子类，覆盖 execute()）
2. `planner/metrics/__init__.py`（新增）— 模块导出
3. `planner/metrics/extractors.py`（新增）— MetricsExtractor + OpenAI 提取器
4. `planner/metrics/pricing.py`（新增）— Pricing 价格表
5. `planner/executor.py`（修改）— 填 token_in/token_out/cost_usd 到 ExecutionMetrics + provider_finished event data
6. `cli/plan.py`（修改）— 注入 MetricsRouter（替代 ScoreRouter）
7. `cli/history.py`（修改）— `_describe_event` 显示 token/cost
8. 完整测试

### 不做（V0.9.7+ 推迟）

- ❌ `ai-hub stats` 统计命令（V0.9.7）
- ❌ `query_events(...)` 统一查询接口（V0.9.7）
- ❌ gemini_cli / qoder 的 token 采集（需 Core Freeze 解冻）
- ❌ 动态价格表（从 API / 配置文件加载）
- ❌ 成本告警 / 预算限制
- ❌ Token 累计追踪（跨 plan 聚合）
- ❌ 修改 core/ + router/router.py + providers/

## 测试策略

测试覆盖：
- `test_metrics_router.py`（新增）— MetricsRouter
  - execute() 返回 Result.metadata 含 server_metrics
  - openai_api provider 的 usage 提取
  - 无 raw / raw=None 的容错
  - 失败的 bridge.run() 不提取 metrics
- `test_metrics_extractor.py`（新增）— MetricsExtractor
  - OpenAI HTTP body 提取 usage
  - 非 OpenAI provider 返回空 dict
  - JSON 解析失败容错
  - 按 provider name 分发
- `test_pricing.py`（新增）— Pricing
  - 已知 model 的 cost 计算
  - 未知 model 用 _default 价格
  - token=0 时 cost=0
- `test_executor_metrics.py`（新增/扩展）— PlanExecutor 集成
  - provider_finished event data 含 server_metrics
  - ExecutionMetrics 填充 token_in/token_out/cost_usd
  - 无 metrics 的 provider（gemini_cli）token 为 0
- `test_cli_exec_history.py`（扩展）— timeline 显示 token/cost
- `test_cli_plan.py` / `test_cli_plan_json.py`（更新）— version 0.9.6

**测试隔离**：用 FakeBridge + 模拟 raw 测试，不真实调用 OpenAI API。

目标：测试基线 435 → 480+ passed。

## 兼容性

- `Router` API 不变（MetricsRouter 是子类）
- `ScoreRouter` 保留（`ai-hub ask` 仍用 ScoreRouter）
- `ExecutionEvent` schema 不变（data 是 free-form dict）
- `ExecutionMetrics` API 不变（字段已预留，V0.9.6 只是开始填充）
- `metadata.schema_version` 维持 "1"
- 无 server_metrics 的 provider，token/cost 为 0（向后兼容）

## 风险

| 风险 | 缓解 |
|------|------|
| Router 子类化是否违反 Core Freeze | ADR 论证：扩展 metadata ≠ 修改路由逻辑；route() 不变 |
| OpenAI 价格表过时 | 手动维护，注释标明来源；V0.9.6 是估算非计费 |
| BridgeResult.raw 类型不稳定 | Extractor 按 bridge 类型分发 + try/except 容错 |
| gemini_cli 无法采集 token | 接受为 0；未来 Core Freeze 解冻再补 |
| MetricsRouter 复制 Router.execute 逻辑 | 保持同步；未来重构为 Router.execute 支持 hook |
| cost_usd 误导用户 | ADR + CLI 输出明确标注"估算" |

## 确认问题（发 ChatGPT 审核）

1. **Router 子类化边界**：MetricsRouter 覆盖 execute() 加 server_metrics 到 metadata，不改 route()。是否算违反 Core Freeze "修改 router/ 路由逻辑 ❌"？
2. **MetricsExtractor 返回 dict vs dataclass**：返回 free-form dict（符合 ADR-0018 原则 B/C）vs 定义 ServerMetrics dataclass。哪个更好？
3. **Pricing 价格表手动维护**：V0.9.6 用静态 dict 维护 OpenAI 价格。是否应该从配置文件加载？还是 V0.9.6 保持简单？
4. **gemini_cli 不支持 token**：接受 gemini_cli / qoder 的 token 为 0，只采集 latency_ms。是否合理？还是应该想办法（如改 gemini 命令为 -o json）？
5. **cost_usd 估算 vs 精确**：V0.9.6 的 cost_usd 是基于价格表的估算，不是 Provider 返回的真实成本。是否应在 CLI 输出明确标注"估算"？
6. **MetricsRouter 用于 plan 但 ask 仍用 ScoreRouter**：`ai-hub plan` 用 MetricsRouter（有 metrics），`ai-hub ask` 仍用 ScoreRouter（无 metrics）。这种不一致是否合理？
7. **server_metrics 入 data 还是独立字段**：当前方案把 server_metrics 放在 `ExecutionEvent.data["server_metrics"]`。是否应该在 ExecutionEvent 加独立 `server_metrics` 字段？（倾向不改，遵循 Postel's Law）
8. **V0.9.6 范围克制**：不做 stats 命令 / query_events / 动态价格表 / 成本告警。是否太保守或正好？

## 后续路线

```
V0.9.6  Provider Metrics（本版本）— token/cost 采集
  ↓
V0.9.7  Statistics（query_events 统一查询 + ai-hub stats 命令）
  ↓
V1.0    Workflow Runtime on Event Model
```

---

## 审核状态

> V0.9.6 ADR-0019 Proposed，待 ChatGPT 外部审核。
