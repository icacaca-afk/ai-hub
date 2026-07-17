# ADR-0015: LLM Planner & Planner 语义原则

- **状态**: Accepted（ChatGPT 外部审核 9.95/10 APPROVED）
- **日期**: 2026-07-17
- **里程碑**: V0.9.2
- **关联**: ADR-0008（Core Freeze）、ADR-0013（Planner 骨架）、ADR-0014（CLI + metadata 分层）
- **API Stability**: Experimental
- **ChatGPT 审核**: 9.95/10 APPROVED（2026-07-17）

## 背景

V0.9.0 交付了 `RuleBasedPlanner`（启发式关键词切分），V0.9.1 接入 CLI 并完成 metadata 分层。但 RuleBasedPlanner 有硬限制：

- 只能按「然后 / 接着 / 最后 / then / ;」等显式分隔符切分
- 无法处理隐式多步任务（如「总结这份 PDF 并翻译」——「并」不在切分规则里）
- 无法根据任务语义识别每步的 capability（只能用关键词匹配）
- 无法生成合理的 depends\_on（只能线性链式）

V0.9.2 引入 `LLMPlanner`：用 chat-capable Provider 做语义分解。但在此之前，必须先回答四个原则性问题——这些问题的答案决定 Plan 数据结构和执行器语义，一旦定下后续版本难以回退。

## 暴露的新需求

### 问题 1: Planner 是否允许失败？

**场景**：

```
总结 PDF → 翻译 → 上传 GitHub
```

如果「翻译」失败，是否继续「上传」？

**候选策略**：

- `abort`：遇到第一个失败立即终止，后续步骤标记 `skipped`
- `continue`：继续执行所有步骤，最终 status=`partial`
- `configurable`：用户可选，默认 `continue`

### 问题 2: Planner 是否允许循环？

**场景**：

```
修 Bug → 测试 → (失败) → 重新修 Bug → 测试 → ...
```

**候选策略**：

- `forbidden`：不支持循环，Plan 是线性/DAG
- `bounded`：支持有限次重试（max\_retries）
- `free`：支持任意循环（while）

### 问题 3: Planner 是否允许并行？

**场景**：

```
总结 / 翻译 / 提炼关键词
```

这三步无依赖，可以并行执行。

**候选策略**：

- `sequential`：只支持顺序执行
- `parallel`：支持并行（同一 depends\_on 层级的步骤并行）

### 问题 4: Planner 是否允许依赖（DAG）？

**场景**：

```
step3 depends on step1, step2
```

**候选策略**：

- `linear`：只支持线性链式（step\[i] depends on step\[i-1]）
- `dag`：支持任意 DAG（拓扑排序后执行）

## 决策

### 原则 1: 失败策略 — V0.9.2 采用 `continue`（不可配置）

**决策**：V0.9.2 默认 `continue`，不可配置。

**理由**：

- 与 V0.9.0/V0.9.1 行为一致（当前就是 continue，跑完所有步骤）
- `abort` 需要引入 `skipped` 状态语义和 CLI 展示，增加复杂度
- 配置化（`--on-failure abort|continue`）属于 Workflow Runtime 范畴，留 V1.0

**未来扩展**：V1.0 Workflow Runtime 引入 `failure_policy` 字段到 Plan.metadata，值为 `continue` / `abort` / `retry`。

### 原则 2: 循环 — V0.9.2 `forbidden`，留 V1.0

**决策**：V0.9.2 不支持循环。Plan 是有向无环结构（线性或 DAG）。

**理由**：

- 循环需要「执行 → 观察 → 决策」的反馈回路，属于 Agent Runtime 范畴
- 循环 + LLM Planner 容易失控（LLM 可能生成无限循环）
- V0.9.x 的定位是「单次分解 + 顺序/DAG 执行」，不是自主 Agent

**未来扩展**：V1.0+ Workflow Runtime 引入 `Loop` 节点类型，有 `max_iterations` 强约束。

### 原则 3: 并行 — V0.9.2 `sequential`，留 V0.10

**决策**：V0.9.2 只支持顺序执行，即使 LLM 生成并行步骤也按顺序跑。

**理由**：

- 并行需要线程池 / asyncio，引入并发复杂度
- 并行步骤的聚合语义复杂（部分成功部分失败的展示）
- V0.9.2 重点是把「语义分解」做对，执行模型保持简单

**未来扩展**：V0.10 DAG Executor 引入并行，同一 `depends_on` 层级的步骤并行执行。

### 原则 4: 依赖 — V0.9.2 `linear`（depends\_on 仅记录），留 V0.10

**决策**：V0.9.2 `depends_on` 仍仅记录不消费。LLM 可生成任意 depends\_on，但执行器按顺序跑。

**理由**：

- 与 V0.9.0/V0.9.1 行为一致
- DAG 拓扑排序 + 并行执行是 V0.10 的核心工作，V0.9.2 不提前做
- 让 LLM 先生成 depends\_on 数据，V0.10 直接消费，避免数据结构迁移

### 总结：V0.9.x 的 Planner 语义边界

| 能力   | V0.9.2       | V0.10        | V1.0         |
| ---- | ------------ | ------------ | ------------ |
| 失败策略 | continue（固定） | continue（固定） | configurable |
| 循环   | ❌ forbidden  | ❌ forbidden  | ✅ bounded    |
| 并行   | ❌ sequential | ✅ parallel   | ✅ parallel   |
| 依赖   | linear（仅记录）  | ✅ DAG（拓扑排序）  | ✅ DAG        |

**核心原则**：V0.9.x 是「语义分解 + 顺序执行」，不是 Agent Runtime。每个版本只引入一个执行模型变化。

## LLMPlanner 设计

### 1. 循环依赖问题与解决方案

**问题**：

```
PlanExecutor 持有 Router（用于执行 Step）
LLMPlanner.decompose() 也需要 Router（用于调用 chat-capable Provider 做分解）
```

如果 LLMPlanner 持有 Router，是否构成循环依赖？

**分析**：不是循环依赖。Router 是无状态的（每次 `execute(task)` 独立路由），可以被多个消费者持有。关键约束是：

- LLMPlanner 持有的 Router 与 PlanExecutor 持有的 Router **必须是同一个实例**（共享 Provider 池、Health、Quota）
- LLMPlanner 只在 `decompose()` 阶段调用 Router，不参与 Step 执行

**解决方案**：LLMPlanner 通过构造函数注入 Router（与 PlanExecutor 一样组合持有）。

```python
class LLMPlanner(Planner):
    def __init__(self, router: Router):
        self.router = router  # 与 PlanExecutor 共享同一个 Router 实例

    def decompose(self, task: Task) -> Plan:
        # 1. 构造分解 prompt
        # 2. 用 router.execute(chat_task) 调 LLM
        # 3. 解析 LLM 返回的 JSON → Plan
        ...
```

### 2. LLM Prompt 设计

**输入**：原始 Task.content
**输出**：JSON 数组，每个元素是一个 Step

```json
[
  {
    "content": "总结这份 PDF",
    "capabilities": ["text.summarize"],
    "depends_on": []
  },
  {
    "content": "翻译成英文",
    "capabilities": ["text.translate"],
    "depends_on": ["step-0"]
  }
]
```

**Prompt 模板**（V0.9.2 简化版）：

```
你是任务分解器。把以下任务分解为有序步骤。

任务：{task_content}

可用能力标签：{capabilities_list}

返回 JSON 数组，每个元素含：
- content: 步骤描述（自然语言）
- capabilities: 能力标签列表（从可用标签中选）
- depends_on: 依赖的前置步骤索引（如 ["step-0"]），无依赖则空数组

只返回 JSON，不要其他文字。
```

### 3. 降级策略

**降级链**：

```
LLMPlanner
  ↓ LLM 调用失败 / JSON 解析失败 / 返回非法结构
RuleBasedPlanner
  ↓ 关键词也无法切分
单步 Plan（退化，等价于直接走 Router）
```

**降级触发条件**：

- Router 路由失败（无 chat-capable Provider 可用）
- Provider 执行失败（timeout / error）
- LLM 返回非 JSON
- JSON 结构非法（缺 content / capabilities 不是列表等）
- Step 列表为空

**降级实现**：LLMPlanner 内部持有 RuleBasedPlanner 实例，失败时调用它。

### 4. CLI 接入

**决策**：V0.9.2 默认仍用 `RuleBasedPlanner`，通过 `--llm` 标志显式启用 LLMPlanner。

```bash
ai-hub plan "总结这份 PDF 然后翻译"           # 默认 RuleBasedPlanner
ai-hub plan "总结这份 PDF 然后翻译" --llm     # 使用 LLMPlanner
```

**理由**：

- LLM 调用有成本和延迟，不应默认启用
- 用户应能选择「快速规则分解」还是「语义分解」
- 与 `ask` / `plan` 分离原则一致：显式选择优于自动切换

**未来扩展**：V0.9.3+ 可考虑 `--planner auto`，根据任务复杂度自动选择。但 V0.9.2 不做。

### 5. metadata 扩展

V0.9.2 不新增 metadata 字段（保持 ADR-0014 冻结）。LLMPlanner 的信息通过现有 `runtime.planner` 字段体现：

```python
"runtime": {
    "planner": "LLMPlanner",      # 或 "RuleBasedPlanner"（降级时）
    "router": "ScoreRouter",
    # planner_version: Reserved（V0.9.3+ 引入，用于区分 prompt 版本差异）
}
```

**降级可见性**：如果 LLMPlanner 降级到 RuleBasedPlanner，`runtime.planner` 显示 `RuleBasedPlanner`（实际执行的 planner 类名）。降级事件本身不记录在 metadata（避免膨胀），可通过日志查看。

**planner_version 预留**：未来 LLMPlanner 可能因 prompt 模板迭代产生行为差异（v1/v2/v3 prompt），`planner_version` 字段预留用于区分。V0.9.2 不实现，仅在 ADR 中声明 Reserved。

## 接口变更

| 变更                                        | 类型  | 向后兼容 | 影响范围     |
| ----------------------------------------- | --- | ---- | -------- |
| 新增 `planner/llm_planner.py`（`LLMPlanner`） | 新增  | Yes  | planner/ |
| 修改 `planner/__init__.py`（导出 LLMPlanner）   | 修改  | Yes  | planner/ |
| 修改 `cli/plan.py`（支持 `--llm` 标志）           | 修改  | Yes  | cli/     |
| `core/*`                                  | 不修改 | —    | —        |
| `router/*`                                | 不修改 | —    | —        |
| `providers/*`                             | 不修改 | —    | —        |
| `planner/plan.py`                         | 不修改 | —    | —        |
| `planner/base.py`                         | 不修改 | —    | —        |
| `planner/rule_based_planner.py`           | 不修改 | —    | —        |
| `planner/executor.py`                     | 不修改 | —    | —        |

## 架构验证结果

| 核心模块                            | 是否修改 | 原因                                              |
| ------------------------------- | ---- | ----------------------------------------------- |
| `core/task.py`                  | ❌    | Task 结构不变                                       |
| `core/result.py`                | ❌    | metadata schema 不变（ADR-0014 冻结）                 |
| `router/router.py`              | ❌    | LLMPlanner 组合调用，不改 Router                       |
| `router/score_router.py`        | ❌    | 同上                                              |
| `providers/*`                   | ❌    | LLMPlanner 不感知 Provider 实现                      |
| `planner/plan.py`               | ❌    | Plan/Step 结构不变（depends\_on 已存在）                 |
| `planner/base.py`               | ❌    | Planner ABC 不变                                  |
| `planner/rule_based_planner.py` | ❌    | 作为降级 fallback，不改                                |
| `planner/executor.py`           | ❌    | 执行器不变，LLMPlanner 产出的 Plan 与 RuleBasedPlanner 同构 |
| `cli/plan.py`                   | ✅    | 新增 `--llm` 标志（非 core）                           |
| `planner/llm_planner.py`        | ✅    | 新增文件（本 ADR 核心）                                  |

## 决策

### 1. LLMPlanner 实现范围（V0.9.2）

**做**：

- `LLMPlanner` 类，构造函数注入 Router
- `decompose()` 方法：构造 prompt → 调 Router → 解析 JSON → 生成 Plan
- 降级链：LLM 失败 → RuleBasedPlanner → 单步 Plan
- CLI `--llm` 标志
- 单元测试（mock Router）+ 降级测试

**不做**（推迟）：

- ❌ `--planner auto` 自动选择（V0.9.3+）
- ❌ Step 级别 capability 验证（LLM 可能返回不存在的 capability，V0.9.2 容忍）
- ❌ Plan 缓存（相同 Task 不重复分解，V0.10+）
- ❌ LLM 分解结果的持久化（V0.10+ Execution History）
- ❌ Prompt 模板的用户可配置化（V1.0+）

### 2. Prompt 模板

V0.9.2 使用硬编码 prompt 模板（不可配置）。模板放在独立文件 `planner/prompts.py`（不放 `llm_planner.py` 顶部），因为 V0.9.3 explain-plan / V0.10 planner cache / V1.0 Prompt Version 都会用到 Prompt，独立文件避免后续拆分成本。

```python
# planner/prompts.py
DECOMPOSE_PROMPT_TEMPLATE = """
你是任务分解器。把以下任务分解为有序步骤。
...
"""
```

### 3. JSON 解析容错

**原则**：LLM 输出属于不可信输入（untrusted input），必须经过校验后才能构建 Plan。

```
LLM JSON
    ↓
Schema Validation（结构校验：数组 / 字段类型 / 必填项）
    ↓
Capability Normalization（未知 capability 记 warning 日志，降级 general.chat）
    ↓
Plan Validation（语义校验：step 数量 / content 非空 / depends_on 引用合法 / 无自依赖 / 无重复 step id）
    ↓
Plan
```

**容错规则**：
- LLM 返回非 JSON → 降级 RuleBasedPlanner
- JSON 不是数组 → 降级
- 数组元素缺 `content` → 跳过该元素
- `capabilities` 不是列表 → 默认 `["general.chat"]`
- `capabilities` 含未知标签 → **记 warning 日志**（不静默），该标签降级为 `general.chat`
- `depends_on` 不是列表 → 默认线性链式（与 RuleBasedPlanner 一致）
- `depends_on` 引用不存在的 step_id → 忽略该引用
- `depends_on` 自依赖（step-i 依赖 step-i）→ 忽略
- step 数量超限（>32）→ 截断到前 32 步，记 warning
- step 列表为空 → 降级 RuleBasedPlanner

**PlanValidator 与 Planner 解耦**：Plan Validation 不属于 LLMPlanner，由独立的 `planner/plan_validator.py` 承担。以后 RuleBasedPlanner / Web Planner / REST Planner / Claude Planner 等全部共用一套验证。

```
RuleBasedPlanner │ LLMPlanner │ WebPlanner │ ...
                       ↓
                 PlanValidator
                       ↓
                 PlanExecutor
```

### 4. 测试策略

- **单元测试**（mock Router）：验证 LLM 返回合法 JSON 时正确生成 Plan
- **降级测试**：验证各种失败场景正确降级到 RuleBasedPlanner
- **不跑真实 LLM**：测试用 FakeRouter 返回预设 JSON，避免依赖真实 Provider 和 subprocess 超时

## 经验教训（预测）

- **先定原则再写代码**：失败/循环/并行/依赖四个问题如果在编码时才遇到，往往会做出短视决策（如「先支持循环试试」）。提前在 ADR 中定下 V0.9.x 的边界，让实现保持克制。
- **降级链比单点健壮**：LLMPlanner 不是独立组件，而是「LLM 优先 + 规则兜底 + 单步退化」的链式策略。任何一环失败都有兜底，不会让用户看到「Planner 挂了」。
- **Planner 与 Router 共享实例**：避免了「Planner 自己又搭一套 Router」的重复建设。Router 是无状态调度器，多消费者共享是自然模式。
- **`--llm`** **显式标志**：与 `ask`/`plan` 分离原则一致。LLM 有成本和延迟，用户应能选择。
- **metadata 不膨胀**：LLMPlanner 的信息通过 `runtime.planner` 类名体现，不新增字段。降级事件走日志不走 metadata。

## Consequences

- 新增 `planner/llm_planner.py`，约 150 行（LLMPlanner + 降级链）
- 新增 `planner/prompts.py`，约 30 行（Prompt 模板常量，独立文件）
- 新增 `planner/plan_validator.py`，约 80 行（PlanValidator，与 Planner 解耦）
- 修改 `planner/__init__.py`：导出 LLMPlanner / PlanValidator（2 行）
- 修改 `cli/plan.py`：新增 `--llm` 标志处理（约 15 行）
- 新增 `tests/test_llm_planner.py`：单元测试 + 降级测试（约 150 行）
- 新增 `tests/test_plan_validator.py`：验证规则测试（约 80 行）
- 全量测试预期：210 → ~240+ passed，0 failed
- Core Freeze KPI 保持绿
- 无破坏性变更（LLMPlanner / PlanValidator / prompts 都是新增，RuleBasedPlanner 不变）

## Frozen Impact

- `core/` ✅ 零修改
- `router/router.py` ✅ 零修改
- `router/health_router.py` ✅ 零修改
- `router/score_router.py` ✅ 零修改
- `providers/` ✅ 零修改
- `planner/plan.py` ✅ 零修改
- `planner/base.py` ✅ 零修改
- `planner/rule_based_planner.py` ✅ 零修改
- `planner/executor.py` ✅ 零修改
- `cli/plan.py` ⚠️ 修改（新增 `--llm` 标志，非 core）
- `planner/llm_planner.py` ✅ 新增（本 ADR 核心）
- `planner/prompts.py` ✅ 新增（Prompt 模板，独立文件）
- `planner/plan_validator.py` ✅ 新增（PlanValidator，与 Planner 解耦）

## ChatGPT 外部审核结果（2026-07-17）

**评分**: 9.95 / 10 — **APPROVED**

**逐项评分**:
| 项目 | 评分 |
|------|------|
| Core Freeze | 10/10 |
| Planner 抽象 | 10/10 |
| LLM 降级链 | 10/10 |
| Validator 解耦 | 10/10 |
| Prompt 分层 | 10/10 |
| 测试覆盖 | 10/10 |
| CLI 设计 | 9.5/10 |
| 可扩展性 | 10/10 |
| 长期维护性 | 10/10 |

**6 个确认问题回复摘要**:
1. **Router 共享**：应该共享，Runtime 只有一个 Router。未来若 Router 开始缓存状态需明确标注 Thread Safe。
2. **metadata 降级记录**：赞同保持干净，降级走日志。未来 Execution History 记 planner_trace（Runtime Trace），不进 Metadata。
3. **MAX_STEPS=32**：合理，但建议改为 `DEFAULT_MAX_STEPS` 常量（非 Magic Number），未来可接 CLI `--max-steps` 或 Config。
4. **不支持 DAG**：一点都不保守，是最正确的边界。Planner/Executor/Workflow 是三个不同层。
5. **Prompt Version**：V1.0 必须做，建议 ADR 现在就预留。Execution History 应记录 Planner / Prompt Version / Model / Temperature。
6. **下一步**：不跳 DAG。建议 V0.9.3 CLI 完整化 → V0.9.4 Execution Trace → V0.10 DAG Executor。

**非阻塞建议（供后续版本参考）**:
- **建议一**：Planner Capability 抽象 — 未来用 `planner.decompose` 而非 `general.chat`，避免聊天模型和 Planner 模型绑死。
- **建议二**：PromptBuilder 模式 — 未来 Prompt 越来越长时，用 Builder 模式（System / Instruction / Examples / Output Schema）替代字符串模板。
- **建议三**：`DEFAULT_MAX_STEPS` 常量命名 — 替代 `MAX_STEPS` Magic Number。
- **建议四**：未来 Router 若引入状态缓存需标注 Thread Safe。

