# ADR-0023 ChatGPT 外部审核记录

- **ADR**: [0023-checkpoint-stage.md](../adr/0023-checkpoint-stage.md)
- **里程碑**: V1.0.3
- **审核日期**: 2026-07-18
- **审核方式**: Playwright 1.60-alpha + Chrome 148 via ws URL
- **最终评分**: 9.9 / 10
- **结论**: APPROVED（建议采纳一项文档层调整后进入 Accepted）

---

## 总体评价（ChatGPT 原文摘要）

> "这是目前 V1.x 路线里最自然的一步。"

> "从你描述的 ADR 来看，它遵循了我前两轮一直强调的一个原则：Pipeline 不应该因为新增功能而演化，新增功能应该演化成 Stage。"

> "CheckpointStage 做到了这一点。"

> "不过，相比 RetryStage，这个 ADR 我会比之前更严格一点，因为 Checkpoint 一旦进入 Runtime，就开始涉及恢复（Resume）、一致性、持久化语义，这些约束以后很难改。"

> "我认为这份 ADR 最大的优点有三个：Pipeline 主体没有变化 / Core Freeze 没破 / Storage 仍然只是 Consumer，不变成 Workflow Engine"

---

## 八个问题逐项评分

| # | 问题 | 评分 | 关键评价 |
|---|------|------|----------|
| Q1 | Stage 是否正确 | 10.0 | "真正的 Middleware。完全符合 ADR-0021" |
| Q2 | Storage 直接绑 SQLiteExecutionStore | 9.6 | **唯一扣分**：建议改 ExecutionStore 抽象（Contract 原则 "Storage is Disposable"） |
| Q3 | event_type="checkpoint" | 10.0 | "非常符合整个 Runtime 的 Event Sourcing" |
| Q4 | Snapshot 设计 | 9.8 | 建议明确 "Snapshot 是 Runtime Projection，不是 ExecutionContext Serialization" |
| Q5 | JSON vs Pickle | 10.0 | "JSON。毫无疑问。不要 Pickle" |
| Q6 | Stage 顺序 | 10.0 | 默认 [Retry, Metrics, Checkpoint]，Pipeline 不强制 |
| Q7 | Failure Policy | 9.8 | 建议 Runtime Contract 明确 "Best Effort" |
| Q8 | Tests | 9.9 | 15 tests 方向合理，建议补 6 个边界 |

---

## 采纳的关键调整（必采纳，1 项）

### Q2: Storage 抽象调整（关键建议）

**原设计**：
- ADR 直接绑定 `SQLiteExecutionStore`
- 关键代码草图：`store.append(event)`

**调整后**：
- ADR 用 `ExecutionStore` 抽象（V0.9.5 Protocol）
- 关键代码草图：`store: ExecutionStore`
- 运行时仍然用 `SQLiteExecutionStore` 实现
- Contract 不绑定具体实现，保持 "Storage is Disposable" 原则

**关键引用（ChatGPT）**：

> "Contract 最好不要绑定 SQLite。建议 ADR 用 ExecutionStore。"
> "因为 Runtime Contract 已经说过：Storage is Disposable。"
> "Checkpoint 不应该知道底层：SQLite / Memory / Remote / S3 以后都应该可以。"

**状态**：✅ 必须采纳（ChatGPT 9.6 唯一扣分点）

---

## 采纳的非阻塞建议（4 项）

### 建议 1: 明确 Snapshot 是 Runtime Projection（Q4）

**采纳**：ADR §2 增加明确原则：

> **Snapshot 是 Runtime Projection，不是 ExecutionContext Serialization。**

**目的**：避免未来有人开始 `pickle.dumps(ctx)`

**状态**：✅ 采纳

---

### 建议 2: Runtime Contract MUST NOT serialize

**采纳**：§9.1.4 增加：

- **MUST NOT serialize**: Provider / Bridge / Router / ExecutionContext / Callable / File Handle
- **SHOULD be replayable**: Snapshot 应能被未来 Resume 独立使用，不依赖 Python Object

**状态**：✅ 采纳

---

### 建议 3: 设计原则

**采纳**：ADR §2 增加：

> **Checkpoint is a durability boundary, not an execution boundary.**

**含义**：
- Checkpoint 负责：恢复
- Checkpoint 不负责：控制执行
- 执行还是：Pipeline
- Checkpoint 只是："如果以后 Resume，这里可以继续"

**状态**：✅ 采纳

---

### 建议 4: Runtime Contract 明确 "Best Effort"

**采纳**：§9.1.4 增加：

> **Checkpoint 属于 Best Effort**：
> Execution 成功 → Checkpoint 写失败 → warning → Execution 仍 Success
> 不允许：Execution → Checkpoint Exception → Pipeline FAIL

**状态**：✅ 采纳

---

## 采纳的测试补充（6 项）

1. `test_failed_bridge_result_also_checkpointed`：success=False 也保存（失败可 resume）
2. `test_store_exception_does_not_break_pipeline`：store.append 抛 Exception → Pipeline 一致
3. `test_empty_output_serialization`：空字符串 JSON 正常
4. `test_artifacts_does_not_modify_original`：artifacts 很多不修改原对象
5. `test_none_server_metrics_becomes_empty_dict`：server_metrics=None → JSON {}
6. `test_snapshot_json_round_trip`：to_dict → json.dumps → json.loads 一致

**状态**：✅ 采纳（实施时加入）

---

## ChatGPT V1.0.4 强烈建议

> "V1.0.4 ConditionStage。Condition 不建议放在 Retry 前面讨论。"
>
> "Checkpoint 已经提供：恢复。Condition 再提供：分支。Workflow Runtime 就真正开始形成。"

**状态**：采纳作为 V1.0.4 路线图

---

## 最终评分汇总

| 项目 | 评分 |
|------|------|
| Stage 化设计 | 10.0 |
| Pipeline 扩展一致性 | 10.0 |
| Core Freeze 遵守 | 10.0 |
| Event 模型一致性 | 10.0 |
| Snapshot 设计 | 9.8 |
| Storage 抽象 | 9.6 → 采纳后 10.0 |
| Failure Policy | 9.8 |
| 测试设计 | 9.9 |
| **综合** | **9.9 / 10** |

---

## 采纳决策

- ✅ ADR-0023 → **Accepted**（采纳 Q2 Storage 抽象 + 4 项非阻塞原则 + 6 项测试补充）
- ✅ ADR-0023 §3.3 改 ExecutionStore 抽象
- ✅ Runtime Contract §9.1.4 增加 MUST NOT serialize + SHOULD be replayable + Best Effort
- ✅ ADR §2 增加 3 条设计原则
- ⏭️ V1.0.3 实施（planner/stages/checkpoint_stage.py + 15+6 tests）
- ⏭️ V1.0.4 ConditionStage 路线图采纳

---

## 前序基线

- **V1.0.2 RetryStage 代码**: 9.95/10 FINAL APPROVED（a5fb64b）
- **V1.0.2 ADR-0022**: 9.9/10 FINAL APPROVED（e59e624）
- **V1.0.1 ExecutionPipeline 代码**: 10.0/10 FINAL APPROVED（670e84b）
- **V1.0.1 ADR-0021**: 9.95/10 FINAL APPROVED（1083145）
- **V1.0 ARCHITECTURE.md**: 10.0/10 FINAL APPROVED（1aeb8c9）
- **Runtime Contract**: 10.0/10 FINAL APPROVED（ce3e7fb）
