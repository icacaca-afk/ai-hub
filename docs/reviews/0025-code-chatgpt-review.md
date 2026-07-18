# V1.0.5 PipelineHooks — ChatGPT Code Review (9.93/10 APPROVED)

**Date:** 2026-07-18
**Reviewer:** ChatGPT (external)
**Code Reviewed:** Commit `75c90c6` (V1.0.5 PipelineHooks implementation)
**Verdict:** **APPROVED — Production Ready, ready to merge**

---

## 1. Score

**9.93 / 10**

> "整体来看，这一版 V1.0.5 PipelineHooks 已经和前面的 Retry / Checkpoint / Condition 保持了相同的设计哲学，没有出现新的架构分叉... Production Ready（V1.0.x 可以合并）"

扣分主要来自两个非常小的长期设计点，而不是当前实现的问题。

## 2. Sub-Scores

| 项目 | 评分 | 说明 |
|------|------|------|
| Architecture | 10/10 | Hook 与 Stage 完全分离 |
| Runtime Contract | 10/10 | Observer 边界清晰 |
| Pipeline Integration | 9.8 | Pipeline.run() 有少量重复代码 |
| API Stability | 9.9 | Hook Signature 很稳定 |
| Best Effort | 10 | 与 Retry / Checkpoint 一致 |
| Core Freeze | 10 | planner 内扩展，非常漂亮 |
| Tests | 9.8 | 已很充分，仅缺极少数异常路径 |

**最终：9.93 / 10** — 属于可以合并的版本。

## 3. Q&A Response

### Q1: Pipeline.run() 是否耦合？ → 轻微，可优化

> 唯一可以进一步优化的地方。目前 before/after_pipeline + for stage:before/try/except/on_error/after/after_pipeline 这一套逻辑以后会继续复制（V1.0.6 StageDescriptor, V1.1 Async, V1.2 Parallel Stage）。

**建议：** 抽成 `_run_stage(stage, ctx)` 内部方法，Pipeline.run() 就只负责 `for stage: ctx = self._run_stage(stage, ctx)`。
**优先级：** 非阻塞。V1.0.6 可做。

### Q2: `_get_stopped_by` 放哪里？ → 保持 Pipeline

> 放 Pipeline 更合理。它不是 Hook 的知识，它是 ExecutionContext 里面 metadata 的解释规则。Hook 不应该知道 `condition_eval` 这种 Metadata Schema。Hook 应该收到 `stopped_by` 即可。否则 Hook Layer 开始理解 Runtime Metadata，这是反方向依赖。

**优先级：** Adopt。当前设计正确。

### Q3: Hook Exception 处理 → 保持 warning+continue

> Logger 崩了 / Tracing 崩了 / Prometheus 崩了 / Pipeline 不应该失败。这是 Runtime 设计基本原则。
> V2 增加 HookErrorPolicy (LOG_ONLY/IGNORE/RAISE)，但不要进入 V1.x。

**优先级：** Adopt。建议 V2 增加 HookErrorPolicy。

### Q4: on_error 时机 → 保持当前

> 不要改 finally。finally 已经没 Exception Context，Hook 很可能需要 traceback / locals / ctx，放 finally 会越来越复杂。

**优先级：** Adopt。

### Q5: Hook API 是否稳定？ → 已足够稳定

> 6 个 Hook 是 V1.x 最稳定的一组。**重要建议：以后不要继续增加 before_retry / after_retry / before_checkpoint 这种**，否则 Hook 会无限膨胀。真正应该做的是：StageDescriptor + event.type 统一事件。不是增加 Hook。

**优先级：** Adopt。V2 收敛为 StageDescriptor。

### Q6: `is_empty()` deprecation → V1.x 一直保留

> 这是非常正常的兼容策略。V2 删掉。不要在 V1.0.6 就删，否则没意义。

**优先级：** Adopt。

### Q7: 测试覆盖 → 已充分，建议补 2 个

**建议 1（采纳）：** Hook 顺序保证 + 异常后 FIFO 继续（A fail, B skip → C 继续）
**建议 2（采纳）：** Stage 抛异常时 after_stage 不执行（before_stage → on_error → raise，after_stage 跳过）
**优先级：** 非阻塞，建议补充。

### Q8: 架构评价 → 极好

> 这一版最大的价值：Pipeline 开始拥有 Behavior (Stage) 和 Observation (Hook) 两条轴。以后 Tracing / Telemetry / Metrics / Audit / Logger / Profiler / Debugger 都会挂 Hook。这是非常好的分层。我不会再拆 Hook Registry ADR，至少 V1.x 没必要。

**优先级：** Adopt。

### Q9: Performance → 完全不用优化

> 每个 Stage `if hooks.enabled` 一次判断。Python bool 几十纳秒。真正耗时是 Bridge，不是 bool。完全不用优化。V2 可用 NullHooks 模式（空实现），但属于 Micro Optimization。

**优先级：** Adopt。V2 引入 NullHooks。

### Q10: StageDescriptor 兼容性 → Forward Compatible

> 目前 Hook 已经很容易迁移。未来 `before_stage(ctx, descriptor)` 替换 `before_stage(ctx, name)` 即可。不存在阻塞，Forward Compatible。

**优先级：** Adopt。V2 引入 StageDescriptor。

## 4. Adopt / Defer Summary

| 建议 | 优先级 | 状态 |
|------|--------|------|
| 抽出 `_run_stage()` 包装 Hook 生命周期 | 非阻塞 | V1.0.6 采纳 |
| 保持 `_get_stopped_by()` 在 Pipeline | Adopt | 当前设计正确 |
| 保持 Hook Best Effort | Adopt | 不修改 |
| HookErrorPolicy (LOG_ONLY/IGNORE/RAISE) | Defer | V2 |
| NullHooks 替代 enabled 判断 | Defer | V2 |
| StageDescriptor 替代 stage_name | Defer | V2 |
| 增加 Hook 调用顺序断言测试 | 非阻塞 | **采纳 (本 commit)** |
| 增加 after_stage 不在异常路径执行的测试 | 非阻塞 | **采纳 (本 commit)** |

## 5. V1.0.6 路线建议 (来自 ChatGPT)

> 如果继续沿着当前架构演进，我不会再增加新的 Stage，而会开始收敛 Runtime 元数据和 Stage描述能力。

V1.0.6 聚焦于：
1. **StageDescriptor**：用统一描述对象替代基于 `stage.name` 的字符串约定，为未来扩展（分类、能力标签、可观测性）打基础。
2. **统一 Runtime Metadata Schema**：把 `condition_eval` / `server_metrics` / `stopped_by` 等零散元数据规范化，避免后续不同 Stage 自定义键名。
3. **Pipeline 内部辅助方法收敛**：把 Stage 执行与 Hook 生命周期封装为内部方法（`_run_stage`），降低 Pipeline.run() 的复杂度，为未来异步或并行执行预留空间。

## 6. 总体结论

> **评分：9.93 / 10**
> **结论：APPROVED（可合并）**
>
> 我没有看到任何会阻止合并的架构问题。当前实现与 ADR-0021～ADR-0024 保持了一致的设计风格：Stage 负责改变运行时状态，Hook 负责观察生命周期，ExecutionStore 负责持久化，三者职责边界清晰。现有建议均属于非阻塞优化或 V2 演进方向，不建议因为这些调整推迟 V1.0.5 合并。

## 7. V1.0.5 状态

**本 commit (V1.0.5 Accepted) 采纳：**
- ✅ 2 项非阻塞测试补充（Hook 顺序断言 + after_stage 异常路径）
- ✅ Hook Best Effort / 6 类 API / FIFO / enabled 属性 全部保留
- ✅ `_get_stopped_by` 保留在 Pipeline（不挪到 Hook Layer）
- ✅ `is_empty()` V1.x 保留（V2 删除）
- ✅ V1.0.6 路线 (StageDescriptor + Metadata Schema + `_run_stage`) 纳入 roadmap

**V2 Roadmap (不进入 V1.x):**
- HookErrorPolicy (LOG_ONLY/IGNORE/RAISE)
- NullHooks 空实现
- StageDescriptor 替代 `stage_name` 字符串约定
- 统一 Runtime Metadata Schema

**核心架构不变：** Hook is an Observer, NOT a Stage。
