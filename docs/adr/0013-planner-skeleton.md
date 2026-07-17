# ADR-0013: Planner 骨架（多步任务分解 + 子任务路由）

- **状态**: Proposed
- **日期**: 2026-07-17
- **里程碑**: V0.9.0
- **关联**: ADR-0008（Core Freeze）、ADR-0011（Score Router）、ADR-0012（Routing Decision Trace v2）
- **API Stability**: Experimental

## 背景

V0.8.2 Score Router 已交付单步任务的最优 Provider 选择（146 passed）。当前数据流：

```
Task(content/capabilities) → ScoreRouter.route() → Provider → Bridge → Result
```

即「一个 Task = 一次路由 = 一次执行」。但真实用户请求往往是**复合目标**，例如：

> "总结这份 PDF，然后翻译成英文，最后用飞书发给我"

这条请求包含 3 个子任务（总结 / 翻译 / 发送），各自需要不同的 capability 与 Provider。当前架构会把整句话塞给一个 Provider，既无法并行，也无法让「翻译」消费「总结」的产物。

V0.9 引入 **Planner**：在 Router 之前加一层「任务分解」，把复合 Task 拆成有序的 Step 列表，每个 Step 独立路由、独立执行，最后聚合为单个 Result。

### 与「D 方案 / AI OS 愿景」的关系

用户提出的 D 方案把 AI Hub 定位为 Local AI Operating System，包含模型调度、Agent 调度、共享记忆、工作流编排等能力。Planner 正是**工作流编排层的种子**：

- V0.9.0 的 Step 模型预留 `depends_on` 字段（V0.9.0 仅记录不强制），为 V0.10+ 的 DAG 执行留接口
- PlanExecutor 采用组合 Router 的方式（不继承冻结的 Router），未来可替换为「Agent Bus」调度器而不影响 core/
- Plan/Step 数据结构面向未来扩展（context 可承载 Memory Bus 上下文，metadata 可承载 Event Bus 事件标识）

**V0.9.0 严格保持骨架形态**——只做分解 + 顺序执行 + 聚合，不实现 DAG、并行、Memory、Event Bus。这些是 V0.10+ / V1.0+ 的范畴。

## 暴露的新需求

V0.8 的 Task/Result 是「单原子任务」模型，无法表达「多步 + 依赖 + 聚合」。需要新增一层抽象，但**不能改动 core/**（ADR-0008）。

### 1. 多步分解能力

**问题描述**: 复合 Task 需要被拆成多个子 Task，每个子 Task 有独立的 content 与 capabilities。

**结论**: 新增 `Plan` / `Step` dataclass（放 `planner/plan.py`）。Step 是子任务的载体，Plan 是 Step 的有序集合。Step 复用 `core.task.Task` 的字段语义（content/capabilities/context），但**不继承 Task**——避免污染冻结的 Task 抽象。

### 2. 分解策略可插拔

**问题描述**: 分解逻辑可以是规则、LLM、或外部 Agent。V0.9.0 只做规则，但必须能平滑替换为 LLM。

**结论**: 新增 `Planner` 抽象基类（`planner/base.py`），只定义 `decompose(task) -> Plan`。V0.9.0 提供 `RuleBasedPlanner` 实现。V0.9.1+ 再加 `LLMPlanner`（用 ScoreRouter 选一个 chat-capable Provider 来分解）。

### 3. 子任务路由复用现有 Router

**问题描述**: 每个 Step 仍需走「capability → Provider → Bridge → Result」链路。

**结论**: `PlanExecutor` 通过**组合**持有 `Router` 实例（不继承），对每个 Step 调 `router.execute(sub_task)`。这样 ScoreRouter 的评分、Health 过滤、Quota 管理全部复用，Planner 不重写路由逻辑。

### 4. 结果聚合

**问题描述**: 多个 Step 产生多个 Result，需聚合成单个 Result 返回给用户。

**结论**: `PlanExecutor.aggregate()` 把所有 Step 的 output 按顺序拼接，artifacts 合并；任一 Step 失败则 Plan 状态为 `partial`，全部失败为 `failed`，全成功为 `success`。聚合规则在 V0.9.0 极简（顺序拼接），V0.9.1+ 可加 LLM 总结。

## 接口变更

| 变更 | 类型 | 向后兼容 | 影响范围 |
|------|------|---------|---------|
| 新增 `planner/__init__.py` | 新增 | Yes | planner/ |
| 新增 `planner/plan.py`（Plan/Step dataclass） | 新增 | Yes | planner/ |
| 新增 `planner/base.py`（Planner ABC） | 新增 | Yes | planner/ |
| 新增 `planner/rule_based_planner.py` | 新增 | Yes | planner/ |
| 新增 `planner/executor.py`（PlanExecutor） | 新增 | Yes | planner/ |
| 新增 `tests/test_planner.py` | 新增 | Yes | tests/ |
| `core/*` | 不修改 | — | — |
| `router/*` | 不修改 | — | — |
| `providers/*` | 不修改 | — | — |

**CLI 暂不接入**：V0.9.0 仅提供 Python API（`PlanExecutor` + `RuleBasedPlanner`）。`ai-hub plan "..."` 命令留到 V0.9.1，避免骨架阶段引入 subprocess 测试复杂度。

## 架构验证结果

| 核心模块 | 是否修改 | 原因 |
|---------|---------|------|
| `core/task.py` | ❌ | Step 复用 Task 字段语义但不继承，避免污染冻结抽象 |
| `core/result.py` | ❌ | 聚合结果直接构造 Result，使用现有字段 |
| `core/provider.py` | ❌ | Planner 不感知 Provider，只通过 Router 间接调用 |
| `core/registry.py` | ❌ | 不直接查询 Registry |
| `core/capabilities.py` | ❌ | Step.capabilities 仍由 `classify()` 识别（在 RuleBasedPlanner 内调用） |
| `router/router.py` | ❌ | 通过组合持有 Router，不继承不修改 |
| `router/health_router.py` | ❌ | 同上 |
| `router/score_router.py` | ❌ | 同上 |
| `providers/*` | ❌ | Planner 完全不感知 Provider 实现 |

## 决策

### 1. 目录结构

```
planner/
├── __init__.py              # 导出 Plan/Step/Planner/RuleBasedPlanner/PlanExecutor
├── plan.py                  # Plan / Step dataclass
├── base.py                  # Planner 抽象基类
├── rule_based_planner.py    # V0.9.0 默认 Planner（启发式分解）
└── executor.py              # PlanExecutor（顺序执行 + 聚合）
```

### 2. 核心数据结构

```python
# planner/plan.py
@dataclass
class Step:
    step_id: str                             # 形如 "step-0", "step-1"
    content: str                             # 子任务自然语言描述
    capabilities: list[str]                  # 能力标签（由 classify 识别）
    depends_on: list[str] = field(default_factory=list)  # 依赖的前置 step_id（V0.9.0 仅记录）
    context: dict = field(default_factory=dict)          # 子任务上下文
    status: str = "pending"                  # pending / running / success / failed / skipped
    result: Optional[Result] = None          # 执行后填入

@dataclass
class Plan:
    plan_id: str
    task_id: str                             # 关联的原 Task.task_id
    steps: list[Step]
    status: str = "pending"                  # pending / running / success / partial / failed
    created_at: str = ""                     # ISO 时间戳
    metadata: dict = field(default_factory=dict)
```

### 3. Planner 抽象

```python
# planner/base.py
class Planner(ABC):
    @abstractmethod
    def decompose(self, task: Task) -> Plan: ...
```

### 4. RuleBasedPlanner（V0.9.0 唯一实现）

**分解启发式（极简，不做语义理解）**：
- 按「换行 / 中文分号 `；` / `;` / 关键词 `然后|接着|之后|最后|再|and then|then|finally`」切分 content
- 每段 trim 后非空即作为一个 Step
- 单段不可切分 → 返回单步 Plan（退化情况，等价于直接走 Router）
- 每个 Step 的 capabilities 由 `core.capabilities.classify()` 重新识别
- `depends_on` 默认线性链式：`step[i].depends_on = ["step-{i-1}"]`（i>0），V0.9.0 执行器**不消费**此字段

### 5. PlanExecutor

```python
# planner/executor.py
class PlanExecutor:
    def __init__(self, router: Router, planner: Optional[Planner] = None):
        self.router = router
        self.planner = planner or RuleBasedPlanner()

    def execute(self, task: Task) -> Result:
        plan = self.planner.decompose(task)
        plan.status = "running"
        for step in plan.steps:
            step.status = "running"
            sub_task = Task(content=step.content, capabilities=step.capabilities,
                            context={**task.context, **step.context})
            result = self.router.execute(sub_task)
            step.result = result
            step.status = "success" if result.is_success else "failed"
        return self._aggregate(plan, task)

    def _aggregate(self, plan: Plan, original_task: Task) -> Result:
        # 顺序拼接 outputs，合并 artifacts
        # status: 全 success → success；全 failed → failed；混合 → partial
        ...
```

### 6. V0.9.0 范围（严格骨架）

**做**：
- Plan / Step 数据结构
- Planner ABC + RuleBasedPlanner（启发式切分）
- PlanExecutor 顺序执行 + 简单聚合
- 单元测试（FakeProvider / FakeRouter）

**不做**（明确推迟）：
- ❌ LLM 分解（V0.9.1+，需选 chat-capable Provider）
- ❌ DAG 依赖执行（V0.10+，需拓扑排序 + 并行调度）
- ❌ 并行 Step 执行（V0.10+）
- ❌ Memory Bus / Event Bus（V1.0+，D 方案 AI OS 层）
- ❌ CLI 接入 `ai-hub plan`（V0.9.1）
- ❌ LLM 结果总结（V0.9.1+，当前只做顺序拼接）

## 经验教训（预测）

- **组合优于继承**：PlanExecutor 组合 Router，而非继承 ScoreRouter。一旦未来 Router 接口变化或出现 AgentBus，Planner 不受影响。
- **Step 不继承 Task**：避免给冻结的 Task 加字段（如 status/result）。Step 是「可执行 + 可追踪」的扩展概念，与 Task 的「纯输入」职责不同。
- **`depends_on` 先占位**：V0.9.0 记录依赖但不消费，让数据结构向前兼容 V0.10 的 DAG 执行器，避免后续迁移成本。
- **CLI 延后**：骨架阶段先保 Python API 稳定，避免 subprocess 测试拖慢迭代（V0.8 explain-route 已踩过 subprocess 编码坑）。

## Consequences

- 新增 `planner/` 目录，5 个文件，约 250 行代码
- 新增 `tests/test_planner.py`，约 150 行测试
- 全量测试预期：146 → ~160+ passed，0 failed
- Core Freeze KPI（`test_zero_modification_kpi`）保持绿
- 为 V0.9.1（LLM Planner + CLI）、V0.10（DAG + 并行）、V1.0（Workflow + Event Bus）铺路

## Frozen Impact

- `core/` ✅ 零修改
- `router/router.py` ✅ 零修改
- `router/health_router.py` ✅ 零修改
- `router/score_router.py` ✅ 零修改
- `providers/` ✅ 零修改
- `cli/` ✅ 零修改（V0.9.0 不接入 CLI）
