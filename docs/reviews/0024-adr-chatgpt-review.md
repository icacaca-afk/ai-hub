# ChatGPT ADR 审核 — ADR-0024 V1.0.4 ConditionStage 草案

**ADR**: [0024-condition-stage.md](../adr/0024-condition-stage.md) (Proposed → Accepted)
**审核日期**: 2026-07-18
**审核工具**: ChatGPT (gpt-5-thinking) via Playwright v2

---

## 综合评分

**9.9 / 10 — FINAL APPROVED（建议进入 Accepted）**

> "这是我认为 V1 Runtime 四个基础 Stage 的最后一块拼图。到这里，Pipeline 已经不仅仅是一个执行框架，而开始具备 Workflow Runtime 的基本能力。"

> "Condition 最容易掉进一个坑：开始承担 Workflow Engine 的职责。你目前最大的优点就是没有掉进去。整个 ADR 一直保持：Condition 只是一个 Stage。不是 Mini Workflow Engine。这一点非常重要。"

---

## 分项评分

| 项目 | 评分 | 说明 |
|------|------|------|
| Pipeline 扩展一致性 | 10.0 | 第四个 Stage 完美衔接 Retry/Metrics/Checkpoint |
| Condition 抽象 | 10.0 | Callable[[ExecutionContext], bool] 是 Python Runtime 最自然抽象 |
| Core Freeze | 10.0 | 继续 0 修改 core/ + router/ + providers/ |
| Runtime Contract 一致性 | 10.0 | §9.1.5 7 MUST + 4 MUST NOT 清晰 |
| API 克制 | 10.0 | 不做 DSL / 不做 Chain / 不做 Template |
| Stage 顺序 | 9.5 | **采纳**：Checkpoint 总是写（记录 abort），不仅是 abort 时不写 |
| continue/skip/abort 语义 | 9.5 | **采纳**：明确 skip=正常结束 vs abort=主动终止 |
| Metadata 设计 | 10.0 | **采纳**：增加 condition_name 字段 |
| 测试设计 | 9.8 | **采纳**：补 2 个边界测试 |
| V1.x 演进路线 | 10.0 | 路线图清晰：V1.0.5 → WorkflowExecutor |

---

## 关键肯定

### Q1 架构 ✓
> "Condition is a control boundary, not a data boundary. 这是整个 ADR 最重要的一句话。建议甚至可以放到 ADR 开头。"

**采纳 #6**：核心原则放 ADR 标题 + §1 第一句。

### Q2 Condition 抽象 ✓
> "Condition = Callable[[ExecutionContext], bool]。不要 DSL。V1.0 根本不需要。真正需要的是 lambda ctx → bool。这是 Python Runtime 最自然的抽象。"

### Q5 fail-closed ✓
> "完全赞成。Condition: Exception → False。符合 Best Effort。"

### Q6 metadata ✓
> "ctx.metadata.condition_eval。不要 ctx.condition。ExecutionContext 已经开始变复杂。metadata 就很好。"

**采纳 #3**：增加 `condition_name` 字段（方便调试）。

### Q7 Core Freeze ✓
> "继续保持 core/ + router/router.py + providers/ 0 修改。Condition 不要知道 EventBus / SQLite / Checkpoint。保持纯控制。"

### Q9 未来扩展 ✓
> "全部推迟。不要 DSL / Chain / Template / Visual Workflow。现在 Callable 足够。"

---

## 关键调整（采纳）

### 调整 #1（Q3 接近阻塞）: 明确 skip/abort 语义 ✏️

**ChatGPT 反馈**：
> "skip 和 abort 实际上现在都是 ctx.stop=True。区别是什么？建议 ADR 写清楚。"

**采纳**：
- `skip` = 正常跳过（Workflow 正常结束）
- `abort` = 主动终止（Workflow 被异常终止）
- 两者实现都是 `ctx.stop = True`，但语义不同
- Condition metadata 写入 `stopped_by: "condition:skip"` / `"condition:abort"` 区分

### 调整 #2（Q4 接近阻塞）: Checkpoint 总是写（不因 abort 跳过） ✏️

**ChatGPT 反馈**：
> "Workflow 被终止也是 Runtime 的一个事实。如果 abort 没有任何 Checkpoint，恢复时你不知道为什么结束。建议：Condition → metadata.condition_eval → Checkpoint → Pipeline stop。这样 Checkpoint 可以记录 status=aborted, reason=condition。这比没有记录更符合 Runtime Observability。"

**采纳**：
- 移除 CheckpointStage 短路 `ctx.stop`（仅短路 `task=None` / `bridge_result=None`）
- CheckpointSnapshot 增加 `aborted: bool` / `stopped_by: Optional[str]` 字段
- 即使 abort 也要写 Checkpoint（记录 Runtime 事实）
- Checkpoint Stage 调整 ADR §9.1.4 + 实施

### 调整 #3（Q6）: condition_eval 增加 condition_name ✏️

**ChatGPT 反馈**：
> "condition_eval 可以考虑增加 condition_name，以后调试方便。"

**采纳**：
- `ctx.metadata["condition_eval"]` 增加 `condition_name: str` 字段
- ConditionStage.__init__ 增加 `name: str = "condition"` 参数

### 调整 #4（Q8）: 补 2 个边界测试 ✏️

**ChatGPT 反馈**：
> "建议增加两个边界测试：① Condition 修改 metadata 后，Checkpoint 是否能读到 ② Condition 连续执行两次，metadata 是覆盖还是追加。"

**采纳**：
- 测试 #27：Condition 写入 metadata → Checkpoint snapshot 包含 condition_eval
- 测试 #28：Condition 连续执行 → metadata 覆盖（不追加）

### 调整 #5（Q10）: Condition MUST be deterministic ✏️

**ChatGPT 反馈**：
> "建议增加：Condition MUST be deterministic for the same ExecutionContext。原因：Condition 本质应该是纯判断。不是 random()/time()/network()/sleep()。否则 Checkpoint Replay 可能不一致。"

**采纳**：
- Runtime Contract §9.1.5 增加 MUST
- `Condition MUST be deterministic for the same ExecutionContext`

### 调整 #6（Q11）: 核心原则放 ADR 标题 ✏️

**ChatGPT 反馈**：
> "必须写。甚至建议放标题。例如：ADR-0024 ConditionStage (Control Boundary)。正文第一句：Condition is a control boundary, not a data boundary。"

**采纳**：
- ADR 标题改为：`ADR-0024: ConditionStage — Pipeline Workflow Control (Control Boundary)`
- §1 第一句：`Condition is a control boundary, not a data boundary.`

---

## 路线图（ChatGPT 强烈建议）

> "如果 ADR-0024 合并，我建议下一步不要继续增加新的 Stage。而是进入 WorkflowExecutor。原因很简单：目前 Pipeline 已经拥有 Route / Retry / Metrics / Condition / Checkpoint。已经具备构建简单 Workflow 的基础能力。V1.0.5 更适合定义：多 Step 执行 / Step 间状态流转 / Workflow 生命周期，而不是继续向 Pipeline 添加职责。"

**保持路线**：
- V1.0.1 ExecutionPipeline ✓
- V1.0.2 RetryStage ✓
- V1.0.3 CheckpointStage ✓
- **V1.0.4 ConditionStage** ← 当前
- **V1.0.5 WorkflowExecutor** ← 下一站

> "不要继续向 Pipeline 添加职责。"

---

## 结论

**FINAL APPROVED** — 采纳 6 项调整后进入 Accepted。

剩余 1 项关键调整（Checkpoint 总是写）需要回写 ADR-0023 CheckpointStage 行为，**这是 V1.0.4 实施时同步调整的**。
