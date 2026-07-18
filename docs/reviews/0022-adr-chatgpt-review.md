# ADR-0022 ChatGPT 外部审核记录

- **ADR**: [0022-retry-stage.md](../adr/0022-retry-stage.md)
- **里程碑**: V1.0.2
- **审核日期**: 2026-07-18
- **审核方式**: Playwright 1.60-alpha + Chrome 148 via ws URL（绕开 400 错误）
- **最终评分**: 9.9 / 10
- **结论**: FINAL APPROVED（ADR 层，可进入代码实施）

---

## 总体评价（ChatGPT 原文摘要）

> "这是我认为继 ADR-0021 ExecutionPipeline 之后最自然、最符合演进路线的 ADR。最重要的是，它没有为了加入 Retry 而回头修改 Pipeline 本身，这一点说明 V1.0.1 的 Pipeline 抽象已经经受住了第一次真正的扩展验证。"

ChatGPT 主要审查了三个方面：

1. Retry 是否是真正独立的 Stage（不是 Pipeline 特例） → **是**
2. 是否为了 Retry 污染 ExecutionContext 或 Pipeline 接口 → **未污染**
3. 是否会影响后续 CheckpointStage、ConditionStage → **不影响**

> "从你的设计来看，答案基本都是'不会'。这说明 Pipeline 的扩展模型已经开始稳定。"

---

## 十个决策逐项评分

| # | 决策 | 评分 | 关键评价 |
|---|------|------|----------|
| 1 | RetryStage 独立（不改 Pipeline） | ★★★★★ | "最理想的 Middleware 关系" |
| 2 | ExecutionContext 不增 retry 字段 | ★★★★★ | "YAGNI。现在不要污染 Context。" |
| 3 | is_retryable() 函数式 | ★★★★☆ | **唯一扣 0.1 分**：默认"安全可重试" |
| 4 | 4 种字符串退避策略 | ★★★★★ | "不要 Callable。字符串：很好。" |
| 5 | Core Freeze | ★★★★★ | "ADR-0021 设计：成功。" |
| 6 | Metrics 行为不变 | ★★★★★ | "Metrics 不知道 Retry。Retry 不知道 Metrics。" |
| 7 | API Stability 实验性 | ★★★★★ | "Retry: Experimental。Backoff: Stable。很好。" |
| 8 | 15 个测试 | ★★★★★ | "合理。" |
| 9 | Runtime Contract 影响 | ★★★★★ | "只增加 Retry 原则。未改六原则。很好。" |
| 10 | Stage 顺序 [Retry, Metrics] | ★★★★★ | "我最满意的一点。" |

---

## 八个确认问题逐项回答

| # | 问题 | ChatGPT 回答 |
|---|------|--------------|
| Q1 | 不改 Pipeline 主体 | 赞同："如果 Retry 需要改 Pipeline，说明 Pipeline 设计失败。目前：没有。很好。" |
| Q2 | Context 不增 retry 字段 | 赞同："保持最小。以后 Checkpoint 真的需要再加。" |
| Q3 | is_retryable 函数 | **建议修改默认策略**（不是 ALL，而是 Safe Retry）—— **唯一建议** |
| Q4 | 字符串策略 | 赞同："不要 Callable。V1：四种：够了。" |
| Q5 | 默认关闭 Retry | 赞同："这是一个库，不是应用。默认：不开启。最安全。" |
| Q6 | 默认 3 次 | 赞同："3 比 5 合理。尤其 LLM：一次：几十秒。5 次：太长。" |
| Q7 | Delay 100ms/5000ms | 赞同："100ms / 5000ms 合理。" |
| Q8 | Scope 克制 | 赞同："不要 Retry + Checkpoint 一起。保持一个 ADR 一个能力。" |

---

## 采纳的 1 项调整

### Q3 调整：is_retryable 默认"安全可重试"（**实施前采纳**）

**原设计**（Proposed）：默认所有失败都可重试。

**调整后**（Accepted）：默认仅"安全可重试"错误重试。

**默认安全重试策略**：

```python
SAFE_RETRY_PATTERNS = {
    "TimeoutError",          # 网络超时
    "ConnectionError",       # 连接失败
    "RateLimitError",        # 限流 (429)
    "ServiceUnavailableError",  # 5xx
    "InternalServerError",      # 5xx
    "BadGatewayError",          # 5xx
    "GatewayTimeoutError",      # 5xx
}

def _default_retryable(br: BridgeResult) -> bool:
    if br.success:
        return False
    # 检查 error type
    if br.error_type in SAFE_RETRY_PATTERNS:
        return True
    # 检查 status_code: 5xx 全部 + 429 限流
    status_code = br.raw.get("status_code") if br.raw else None
    if status_code is not None:
        return status_code >= 500 or status_code == 429
    return False
```

**不重试的常见错误**（LLM Provider 永久错误）：
- 401 Unauthorized: api key 无效
- 403 Forbidden: 权限不足
- 404 Not Found: model 不存在
- 400 Bad Request: 参数错误
- quota exhausted: 配额耗尽
- validation: 输入验证失败

**用户完全覆盖能力**：
```python
RetryStage(is_retryable=lambda br: True)  # 重试所有错误
```

---

## ChatGPT 额外 2 项非阻塞原则建议

### ① Retry 应明确幂等性要求（推荐加入 Runtime Contract）

> "RetryStage SHOULD only retry idempotent bridge executions, or providers whose retry semantics are known to be safe."

**状态**：采纳（写入 Runtime Contract §10）

### ② Retry 应记录 Attempt Metadata（但不进入 Context）

> "BridgeResult 或者 Result.metadata 增加 retry_attempts / retry_delay_ms。"

**状态**：V1.1 评估（V1.0.2 不实施）

---

## V1.0.3 建议（CheckpointStage）

> "Checkpoint 不要保存 Pipeline。应该保存 ExecutionContext Snapshot。例如：Task / Provider / Bridge / Result / Server Metrics。"

**状态**：记录在 V1.0.3 ADR-0023 草案规划中（未来实施）。

---

## 最终评价（ChatGPT 原文）

> "ADR-0022 没有引入新的架构层，也没有修改 Pipeline 核心，而是验证了 Pipeline 的扩展机制确实可用。这正是我希望看到的演进方式。"

> "我唯一建议调整的是默认重试策略：不要默认'所有错误都可重试'，而应默认采用'安全可重试'的策略，同时保留用户通过 is_retryable 完全覆盖默认行为的能力。"

> "除此之外，这份 ADR 与 ADR-0021、Runtime Contract、ARCHITECTURE.md 保持一致，范围控制也很克制。"

---

## 采纳决策

- ✅ ADR-0022 → **Accepted**（采纳 Q3 is_retryable 默认"安全可重试"调整）
- ✅ Runtime Contract 同步更新（§9 新增 V1.0.2 行 + 新增 RetryStage 原则 + 新增幂等性原则）
- ⏭️ 实施 V1.0.2 代码（planner/stages/retry_stage.py + test_retry_stage.py）
- ⏭️ 实施完成后发 ChatGPT 代码层审核

---

## 前序基线

- **V1.0.1 ExecutionPipeline**: 10.0/10 FINAL APPROVED（670e84b）
- **V1.0.1 ADR-0021**: 9.95/10 FINAL APPROVED（1083145）
- **V1.0 ARCHITECTURE.md**: 10.0/10 FINAL APPROVED（1aeb8c9）
- **Runtime Contract**: 10.0/10 FINAL APPROVED（ce3e7fb）
