# ARCHITECTURE.md ChatGPT 外部审核

> 时间：2026-07-18
> 评分：**10.0 / 10 FINAL APPROVED** ✅
> 提交：3defdb0 docs: ARCHITECTURE.md 草案
> 变更：334 lines，10 章节
> 审核 prompt：`.tmp_architecture_review.txt`（3151 chars，8 个确认问题）
> 回复：约 4500 chars

---

## 总体结论

> 评分：10.0 / 10（FINAL APPROVED）
>
> 这份 ARCHITECTURE.md 达到了我之前建议它承担的职责：**它是项目的入口，而不是规范本身**。
>
> 我特别认可的一点是，你没有把它写成另一本 Runtime Contract，也没有把所有 ADR 内容重新复制一遍，而是把它定位成：
>
> - **Architecture** = 项目全景图
> - **Runtime Contract** = 行为约束
> - **ADR** = 设计决策历史
>
> 这是三者最合理的职责划分。

---

## ChatGPT 对文档体系的最终判断

> 现在整个文档体系已经形成了比较完整的层次：
>
> ```
> README
>     │
>     ▼
> ARCHITECTURE.md
>     │
>     ├──────── Runtime Contract
>     │
>     ├──────── Provider Spec
>     │
>     ├──────── ADR
>     │
>     ├──────── Reviews
>     │
>     └──────── (未来) Workflow Contract
> ```
>
> **建议新贡献者阅读顺序**：
> README → ARCHITECTURE → Runtime Contract → Provider Spec → ADR
>
> 这已经是一套成熟项目常见的阅读路径。

---

## ChatGPT 对 Architecture / Contract / ADR / Code 的职责划分

| 文档 | 职责 |
|------|------|
| README | 告诉别人：是什么 |
| **ARCHITECTURE** | 告诉别人：怎么组成 |
| **Runtime Contract** | 告诉别人：运行必须遵守什么 |
| **ADR** | 告诉别人：为什么这样设计 |
| **Code** | 真正实现 |

> 这是一个非常健康的文档体系。

---

## 逐项反馈（8 个确认问题）

### Q1 10 章节结构 — ✅ 合理

> 唯一建议：**不要加入 Quick Start**。
>
> Quick Start 属于 README（Tutorial）。
> Architecture 属于 Explain，不是 Tutorial。
>
> 把 `pip install` / `python ...` 塞进 Architecture，文档职责就开始混乱。
>
> 所以：保持 Overview-only。

**结论**：维持 10 章节，不加 Quick Start。

### Q2 AI Runtime 定位 — ✅ 准确

> **AI Runtime 比 Agent Runtime 更准确**。
>
> 原因：现在 AI Hub 其实支持 Task → Provider → Bridge → Result。
> Agent 只是未来的一种 Task。
>
> 如果写 Agent Runtime，容易让人误认为 Agent/Memory/Planning/Tool Calling 才是中心。
> 实际上你的 Runtime 是 Task Runtime，Agent 只是 Task Producer。

**结论**：维持 "AI Runtime" 定位。

### Q3 OmniRoute 对比 — 📝 弱化

**采纳**：从"对比"改为"Related Runtime Patterns"。

**原文**：

> 与 OmniRoute / 类似项目的区别（6 维度对比表）

**改为**：

> Related Runtime Patterns（Gateway / Runtime / Workflow Engine / Agent Framework）
> 把 OmniRoute 放其中一项。

**原因**：

- "对比" 容易让人理解为竞品
- "定位不同" 是真正想表达的
- 文档寿命更长（不因某个项目变化而过时）

### Q4 ASCII vs Mermaid — ✅ 保留 ASCII

> **保留 ASCII**。
>
> ASCII：GitHub / Terminal / PDF / Diff / Review 全部支持。
> Mermaid：GitHub 支持很好，但很多 IDE / PDF / Markdown Viewer 支持不统一。
>
> 建议：Architecture 保留 ASCII，以后如果 README 想更漂亮，再加 Mermaid。两者可以共存。

**结论**：维持 ASCII 流程图。

### Q5 V1.0 路线 — ✅ 顺序正确

> 我会保持：Pipeline → Retry → Checkpoint → Condition → Provider
>
> 原因：
> - Condition 依赖 Execution Pipeline
> - Checkpoint 依赖 Retry
> - OmniRoute Provider 完全可以最后（属于生态，不是 Runtime Core）

**结论**：维持 V1.0.1~V1.0.4 顺序。

### Q6 文档体系 — 📝 建议增加 3 个文档

**采纳（V1.0 启动时新增）**：

**① GLOSSARY.md**（最推荐）
- 统一术语：Task / Plan / Step / ExecutionEvent / ExecutionMetrics / server_metrics / Bridge / Provider / Capability / Pipeline
- 避免一个词多个解释

**② DEVELOPMENT.md**
- 如何新增 Provider
- 如何新增 Bridge
- 如何新增 CLI
- 如何新增 Consumer

**③ TESTING.md**
- 测试分层：Unit / Integration / CLI / External
- 以后测试越来越多，这份文档会很有价值

### Q7 V0.9.x 收官总结 — 📝 增加 "Next Milestone"

**采纳**：在 §9 增加 V1.0 Next Milestone 短章节。

**示例**：

> V1.0 Goal：
> - Execution Pipeline
> - Retry
> - Checkpoint
>
> 帮助读者理解：为什么 V0.9 到这里结束。

### Q8 5 分钟理解项目 — 📝 增加 "Typical Use Cases"

**采纳**：增加 "Typical Use Cases" 章节（半页以内）。

**示例**：

```
User Task → Planner → Execution → Event → History → Statistics
```

帮助读者理解：AI Hub 到底解决什么问题。

---

## ChatGPT 唯一建议新增的一张图

**采纳**：拆分 **Static Architecture** 和 **Runtime Flow**。

> 如果允许增加一张图，我会加：
>
> **Static Architecture** 和 **Runtime Flow** 分开。
>
> 静态：Planner / Router / Provider / CLI（组件视图）
> 运行：Task → Plan → ExecutionEvent → SQLite → Statistics（数据流视图）
>
> 目前很多 Architecture 文档容易混。
> 如果分开，Architecture 会更专业。

**采纳**：在 §2 拆分为 §2.1 静态架构 + §2.2 运行时数据流（基本已是这个结构，但更明确命名）。

---

## ChatGPT 对 V0.9.x → V1.0 过渡的最终建议

> 如果把整个 V0.9.x 看成一个阶段，我认为目前已经具备了进入 V1.0 的条件：
>
> - **运行时模型**：ExecutionEvent、EventBus、ExecutionMetrics 等核心概念已经稳定。
> - **观测与分析能力**：Trace、SQLite 持久化、Metrics、Statistics 已形成完整闭环。
> - **架构与约束**：Runtime Contract 和 ARCHITECTURE.md 已将关键原则文档化，降低后续演进破坏既有设计的风险。
>
> 因此，我建议将 V1.0 的第一个 ADR 聚焦于 ExecutionPipeline，继续保持你在 V0.9.x 建立的节奏：
> **ADR → 审核 → 实现 → 测试 → 冻结**。
>
> 不需要预先设计整个 Workflow Runtime，再逐步扩展 Retry、Checkpoint、Condition 等能力即可。

---

## 采纳清单

| # | 建议 | 状态 | 落地位置 |
|---|------|------|---------|
| 1 | 不加 Quick Start（保持 Overview-only） | ✅ 维持 | §1-10 |
| 2 | 维持 AI Runtime 定位 | ✅ 维持 | §1 |
| 3 | 对比表弱化为 Related Runtime Patterns | 📝 采纳 | §1 末尾 |
| 4 | 维持 ASCII 流程图 | ✅ 维持 | §2 |
| 5 | 维持 V1.0.1~V1.0.4 顺序 | ✅ 维持 | §8 |
| 6 | 增加 GLOSSARY.md / DEVELOPMENT.md / TESTING.md | 📝 V1.0 任务 | §7 文档体系 |
| 7 | V0.9 收官表增加 Next Milestone | 📝 采纳 | §9 |
| 8 | 增加 Typical Use Cases 章节 | 📝 采纳 | 新增章节 |
| 9 | 拆分 Static Architecture vs Runtime Flow | 📝 采纳 | §2 |

**采纳 5 项微调 + 1 项拆分 + 3 个未来文档建议**

---

## 下一步

1. → **采纳 5 项微调更新 ARCHITECTURE.md**
2. → commit Accepted 状态 + review 记录
3. → V1.0 启动：写 GLOSSARY.md + ADR-0021 ExecutionPipeline
4. → 编码 → 测试 → 审核 → 冻结

---

## V0.9.x 完整演化线（最终）

| 版本 | 主题 | 评分 |
|------|------|------|
| V0.9.0~V0.9.2 | Planner Skeleton → LLM Planner | 9.5/10 |
| V0.9.3 | Inspect / PlanStore | 9.98/10 |
| V0.9.4 | ExecutionEvent / Trace | 10.0/10 + 10.0/10 |
| V0.9.5 | SQLiteExecutionStore | 10.0/10 + 10.0/10 |
| V0.9.6 | Provider Metrics | 9.95/10 + 10.0/10 (Final) |
| V0.9.7 | Execution Analytics | 9.95/10 + 10.0/10 (Final) |
| **Runtime Contract** | **运行时约定** | **10.0/10 (Final)** |
| **ARCHITECTURE.md** | **文档体系入口** | **10.0/10 (Final)** |

**V0.9.x → V1.0 全部就绪。V1.0 启动条件满足。**
