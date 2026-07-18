# ADR-0022 V1.0.2 RetryStage — ChatGPT 代码层审核记录

- **ADR**: [0022-retry-stage.md](../adr/0022-retry-stage.md)
- **实施 commit**: 07acfe1
- **审核日期**: 2026-07-18
- **审核方式**: Playwright 1.60-alpha + Chrome 148 via ws URL
- **最终评分**: 9.95 / 10
- **结论**: FINAL APPROVED（可进入 Accepted）

---

## 总体评价（ChatGPT 原文摘要）

> "这一版基本符合 ADR-0022 当初的设计目标，而且有一点我认为尤其重要：你证明了 ExecutionPipeline 的扩展点是真实可用的，而不是为了设计而设计。"

> "V1.0.1 的价值并不是 Pipeline 本身，而是后续新增 RetryStage 时 Pipeline 主体几乎不用改。这一点已经成为 ADR-0021 是否成功的最好验证。"

> "这一版最大的优点不是 Retry，而是保持了整个 Runtime 的几个约束没有被破坏：Core Freeze 没动 / Router.execute() 没动 / ExecutionContext 没污染 / Pipeline.run() 没改逻辑 / Retry 完全作为 Stage 插进去。"

> "这说明 Pipeline 已经真正变成 Extension Point，而不是新的耦合中心。这是我上一轮 ADR 最希望看到的结果。"

---

## 八个问题逐项评分

| # | 问题 | 评分 | 关键评价 |
|---|------|------|----------|
| Q1 | Stage 思想 | 10.0 | "输入 Context / 输出 Context / 不知道 Pipeline 外面是谁。这就是 Decorator/Middleware 的正确方向" |
| Q2 | is_retryable 实现 | 9.8 | "V1.0 最合理的方案"（raw + error 文本模式），唯一建议：文档化 Priority 1/2/3 |
| Q3 | Backoff | 10.0 | "四种策略已经覆盖 95% 场景" + max_delay_ms 保护"非常关键" |
| Q4 | 异常处理 | 9.5 | "bridge.run Exception → continue 而不是 Pipeline 崩"，建议优化 warning 日志 |
| Q5 | Pipeline 0 修改 | 10.0 | "ADR-0021 真成功了" |
| Q6 | 测试 | 9.9 | 28 tests 总体方向对，建议补 retry=0 / retryable=False / 一直 Exception / max_delay clamp / MetricsStage 反映最终 |
| Q7 | Core Freeze | 10.0 | "完全符合。没有任何问题。这是我最满意的一点" |
| Q8 | Runtime Contract | 10.0 | 建议写成 MUST/MUST NOT 形式（非阻塞） |

---

## 五个非阻塞建议（全部采纳）

### 建议 1: Q2 文档化 Default Retry Policy Priority

**采纳**：在 `retry_stage.py` 顶部 docstring 明确：
```
Default Retry Policy
  Priority 1: raw.status_code (5xx 全部 + 429 限流)
  Priority 2: error message 文本模式匹配
  Priority 3: 保守不重试
```

**状态**：✅ 采纳

---

### 建议 2: Q4 优化 Warning 日志

**采纳**：warning 日志包含：
- `provider=name`
- `attempt=N/M`
- `exception type + message`
- `bridge_result error`

**代码层调整**：
```python
# 当前:
logger.warning("RetryStage attempt %d/%d raised: %s: %s", ...)

# 优化后:
logger.warning(
    "RetryStage provider=%s attempt=%d/%d raised %s: %s",
    ctx.provider.name, attempt, self.max_retries,
    type(e).__name__, str(e),
)
```

**状态**：✅ 采纳

---

### 建议 3: Q6 测试补充

**采纳**：新增测试：
1. `test_retry_disabled_with_max_retries_zero`：max_retries=0 + bridge 失败 → bridge.call_count=0
2. `test_no_sleep_when_not_retryable`：is_retryable=False → 0 次 sleep
3. `test_consistent_attempts_on_persistent_exception`：bridge.run 一直抛异常 → sleep 次数 = attempt 次数
4. `test_max_delay_clamp_exponential`：连续重试直到 delay 触发 max_delay_ms 上限
5. `test_metrics_reflects_final_result_after_retry`：RetryStage + MetricsStage 集成，metrics 来自最后一次成功（不是第一次失败）

**状态**：✅ 采纳

---

### 建议 4: Q8 Runtime Contract 强化 MUST/MUST NOT 风格

**采纳**：调整 §9.1.3 RetryStage 专属原则为 MUST/MUST NOT 形式：
- MUST NOT mutate Task
- MUST NOT mutate Provider
- MUST NOT mutate Bridge
- MUST NOT reroute Provider
- MUST only retry current Bridge
- MUST preserve ExecutionContext immutability

**状态**：✅ 采纳

---

### 建议 5: RetryReport（V1.0.3+ 评估，不进 V1.0.2）

**采纳**：记录 V1.0.3 ADR-0023 CheckpointStage 规划中。

> "不是 V1.0.2 做。而是 ADR-0023 或 ADR-0024 再讨论。"

**状态**：⏭️ 延后到 V1.0.3 评估

---

## 对后续 ADR 的强烈建议（ChatGPT 路线图）

> "现在路线已经非常清晰，我建议不要改变顺序。"

| 版本 | 目标 | 关键不变量 |
|------|------|-----------|
| V1.0.3 | CheckpointStage | Pipeline 可以暂停。**不要加入 Retry 改动** |
| V1.0.4 | ConditionStage | Pipeline 可以分支。**不要加入 Retry** |
| V1.1 | TimeoutStage | 超时控制 |
| V1.2 | CircuitBreakerStage | 熔断保护 |
| V2 | Async Pipeline | 异步流水线 |

**状态**：采纳作为 V1.x 路线图

---

## 各项评分汇总

| 项目 | 评分 |
|------|------|
| Pipeline 扩展性验证 | 10.0 |
| RetryStage 设计 | 10.0 |
| Core Freeze 遵守 | 10.0 |
| Backoff 策略 | 10.0 |
| is_retryable 默认策略 | 9.8 |
| 测试覆盖 | 9.9 |
| Runtime Contract 一致性 | 10.0 |
| API 克制 | 10.0 |
| **综合** | **9.95 / 10** |

---

## 关键评价（ChatGPT 原文）

> "这是一个成熟、边界清晰的 ADR 实施。最大的价值不只是新增了 Retry，而是证明了 ExecutionPipeline 已经具备通过 Stage 持续扩展能力，无需反复修改 Pipeline 核心。这为后续的 CheckpointStage、ConditionStage、TimeoutStage 等演进提供了稳定基础。"

> "唯一建议均属于文档、日志和未来可观测性的增强，不构成合并阻塞。"

---

## 采纳决策

- ✅ ADR-0022 V1.0.2 代码 → **Accepted**
- ✅ 采纳 4 项非阻塞调整（Q2 docstring / Q4 warning / Q6 测试 / Q8 Runtime Contract）
- ⏭️ RetryReport → V1.0.3+ 评估
- ✅ V1.x 路线图采纳（V1.0.3 CheckpointStage → V1.0.4 ConditionStage → V1.1 Timeout → V1.2 CircuitBreaker → V2 Async）

---

## 前序基线

- **V1.0.1 ExecutionPipeline 代码**: 10.0/10 FINAL APPROVED（670e84b）
- **V1.0.1 ADR-0021**: 9.95/10 FINAL APPROVED（1083145）
- **V1.0 ARCHITECTURE.md**: 10.0/10 FINAL APPROVED（1aeb8c9）
- **V1.0 Runtime Contract**: 10.0/10 FINAL APPROVED（ce3e7fb）
- **V1.0.2 ADR-0022**: 9.9/10 FINAL APPROVED（e59e624）
