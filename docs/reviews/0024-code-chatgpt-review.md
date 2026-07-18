# ChatGPT 代码层审核 — ADR-0024 V1.0.4 ConditionStage 实施

**实施 commit**: d8f959d "feat: V1.0.4 ConditionStage 实施"
**测试基线**: 350 passed 关键测试, 0 failed (30 condition + 4 V1.0.4 aborted + 24 checkpoint + 39 pipeline + 34 retry + 219 其他)
**审核日期**: 2026-07-18
**审核工具**: ChatGPT (gpt-5-thinking) via Playwright v2

---

## 综合评分

**9.95 / 10 — FINAL APPROVED（建议合并）**

> "这是目前你 V1.x 路线里，第一个真正证明 ExecutionPipeline 架构价值的版本。"

> "V1.0.1 证明 Pipeline 能替代 Router。V1.0.2 证明 Pipeline 可以增加 Retry 而不修改主体。V1.0.3 证明 Pipeline 可以增加 Persistence。V1.0.4 则证明 Pipeline 可以承载 Workflow Control。"

> "这四个 ADR 连起来以后，我认为 ExecutionPipeline 设计已经基本成立，不再是一个"为了 Stage 而 Stage"的抽象，而是真正形成了可扩展 Runtime。"

---

## 分项评分

| 维度 | 分数 |
|------|------|
| Architecture | 10.0 |
| Pipeline 扩展性 | 10.0 |
| Condition 抽象 | 10.0 |
| Runtime Contract 一致性 | 10.0 |
| Core Freeze | 10.0 |
| Workflow Runtime | 10.0 |
| Checkpoint 协同 | 9.8 |
| Pipeline.run 修改 | 9.7 |

**最终：9.95 / 10**

---

## 关键肯定

### 架构 — Pipeline 已成为 Runtime ✓

> "以前 Pipeline 负责: Route → Bridge → Metrics → Checkpoint。现在变成: Route → Bridge → Retry → Metrics → Condition → Checkpoint"

> "四个 Stage 完全互相不知道存在，全部实现同一个 Protocol，Pipeline 不认识任何 Stage 类型"

> "Pipeline 已经成为 Runtime，而不是 Metrics Runner。这是 ADR-0021 当初设计目标。10/10"

### Condition 抽象稳定性 ✓

> "Callable[[ExecutionContext], bool] 是 V1 最好的抽象。它没有 DSL/AST/JSON/Rule Engine/YAML。只有 callable(ctx)。"

> "以后 DSL: compile → Callable 即可。Condition 永远不用修改。这是最大的价值。10/10"

### skip vs abort 语义 ✓

> "以前 skip 和 abort 实际上没有区别。现在: `condition:foo:skip` / `condition:foo:abort`。Checkpoint 可以记录 Workflow 为什么停止。Replay 可以知道: 这是正常结束还是人为终止。"

### Fail-Closed ✓

> "Workflow Runtime: Condition 出异常 → False。远好于 Pipeline Crash。尤其 AI Workflow: LLM/Regex/Python/Plugin 都可能异常。Fail Closed 是合理默认。10/10"

### metadata 复用 ✓

> "没有新增 ctx.condition / ctx.last_condition / ctx.audit / ctx.history。而是 ctx.metadata 继续承担 Runtime Annotation。这是 Runtime Context 的经典设计。10/10"

### Core Freeze ✓

> "真正修改: 只有 planner/。没有动 core/ / router/ / provider/。Architecture Boundary 保住了。10/10"

### Pipeline 经受住考验 ✓

> "本次最大的成功: Pipeline 没有因为 Condition 被推翻。这说明 ADR-0021 当初的设计经受住了 Retry/Checkpoint/Condition 三个连续 ADR。这是判断一个 Runtime 是否设计成功的重要标准。"

---

## 采纳调整

### 调整 #1 (Q10 采纳): Runtime Contract 增加 "Condition SHOULD avoid external side effects" ✓

**ChatGPT 反馈**：
> "建议增加: Condition implementations SHOULD be free of externally observable side effects. 原因: Condition 最好 读 Context → 返回 bool, 不要 写数据库/发网络/修改文件。否则 Replay 不可预测。"

**实施位置**：`docs/adr/0024-condition-stage.md` §7 Runtime Contract

---

## 不采纳（V1.x 后期 / V2 再说）

| 建议 | 理由 |
|------|------|
| Q3 stopped_by → stop_reason (V2 演进) | V1.0.4 维持 stopped_by 命名, V2 再说 |
| Q4 Stage 元数据 always_run_after_stop | V2 改进, 替代 Pipeline 识别具体 Stage |
| Q9 E2E Workflow 测试 | V1.x 后期补充, 留待 V1.0.5+ |

---

## 关键扣分点（不阻塞）

### Pipeline.run() 修改的轻微耦合（0.05 分）

> "你为了 abort → Checkpoint 修改了 Pipeline.run。实现方式: if stop: 继续寻找 checkpoint。说明 Pipeline 已经知道 Checkpoint 是谁。这是一个轻微的耦合。"

**ChatGPT 建议的 V2 改进**：
```python
# V2: Stage 增加 always_run_after_stop 元数据
class Stage:
    always_run_after_stop: bool = False

class CheckpointStage(Stage):
    always_run_after_stop: bool = True

# Pipeline.run() V2 实现
if stop:
    for stage in remaining:
        if stage.always_run_after_stop:
            ctx = stage(ctx)
# Pipeline 不再认识具体 Stage 类型
```

**当前 V1.0.4 实现**（轻微耦合可接受）：
```python
if stage.name == "checkpoint" and hasattr(stage, "store"):
    ctx = stage(ctx)
```

**理由不立即采纳**：V1.0.4 通过 `name + hasattr` duck typing 保持兼容；V2 引入声明式元数据是更彻底的解耦。

---

## 路线图（ChatGPT 强烈建议）

> "我建议下一步不要再增加新的 Stage 类型，而是开始完善 Runtime 的能力。"

**优先级建议**：
- **V1.0.5**: Pipeline Hooks（before/after），便于日志、Tracing、调试
- **V1.0.6**: Stage Capability Metadata（每个 Stage 声明是否可重放 / 是否终止 / 是否总在 stop 后运行，替代当前对 Checkpoint 的特殊处理）
- **V1.1**: Condition DSL（编译为 Callable），保持 Callable[[ExecutionContext], bool] 作为底层接口

> "本次最大的成功: 真正不是 Condition。而是 Pipeline 没有因为 Condition 被推翻。"

**保持路线**：
- V1.0.1 ExecutionPipeline ✓
- V1.0.2 RetryStage ✓
- V1.0.3 CheckpointStage ✓
- V1.0.4 ConditionStage ✓ (9.95/10)
- **V1.0.5 Pipeline Hooks** ← 下一站

---

## 结论

**FINAL APPROVED** — 0 阻塞项，仅 1 项立即采纳（Runtime Contract 增量），其他建议 V1.x 后期 / V2 再说。

立即进入 V1.0.4 Accepted + 启动 V1.0.5 Pipeline Hooks 草案。
