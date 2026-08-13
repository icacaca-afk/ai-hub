# ADR-0033: Predicate API (PredicateDescriptor)

| Field | Value |
|-------|-------|
| Status | Proposed |
| Date | 2026-08-13 |
| Decider | User + ChatGPT (ADR Review) |
| Supersedes | — |
| Superseded by | — |
| Related | ADR-0024 (ConditionStage), ADR-0031 (Metadata Serialization), ADR-0032 (Pipeline Introspection) |

## 1. Context

### 1.1 背景

V1.0.11 (ADR-0032) 完成了 Pipeline Introspection：`pipeline.describe()` 输出 stages + edges，消费者可以「看见」Pipeline 由哪些 Stage 组成、执行顺序如何。

但存在一个**可观测性断层**：

```json
{"id": "post:1", "name": "condition", "role": "condition", "position": "post", "index": 1}
```

ConditionStage 对消费者仍是**黑盒**——消费者能看到「这里有一个条件控制 Stage」，但**不知道它在判断什么**。

ChatGPT V1.0.11 代码审核明确建议（V1.0.12 路线）：

> 进入 Predicate API / ADR-0033。只回答 "What predicate is this?"，不做 "predicate expression engine"。
> 建议沿 metadata 链：`Predicate →(describe) PredicateDescriptor →(canonical serializer) dict`。
> 顺序合理：V1.0.11 structure → V1.0.12 Predicate semantics → V1.0.13 CLI presentation（因 CLI 层 condition 节点仍是黑盒）。

### 1.2 问题

`ConditionStage.condition` 的类型是 `Condition = Callable[[ExecutionContext], bool]`（ADR-0024 冻结）。

要让消费者理解「这个 predicate 判断什么」，最直觉的做法是 introspect 这个 callable 的源码（`inspect.getsource` / AST 解析 / lambda 反编译）。但这条路是**死路**：

- Python callable 的源码/表达式不是可靠的结构化数据（lambda 无 `__doc__`、闭包捕获、字节码不可移植）
- 一旦允许源码序列化，就会滑向「predicate expression engine」——而 ChatGPT 明确要求**不做** parser / AST / DSL
- 运行时才有的闭包变量，introspection 无法可靠提取

### 1.3 目标

- 引入 `PredicateDescriptor` 不可变值对象，描述 predicate 的**语义元数据**（name / description / subject）
- `ConditionStage.describe_predicate()` 返回 `PredicateDescriptor`
- `serialize_predicate()` canonical 序列化函数（纳入 metadata serialization 层）
- 语义来源 = **用户显式声明**（构造 ConditionStage 时传入），不 introspect callable 源码
- 向后兼容：`ConditionStage` 现有构造签名不变，新参数全部可选

### 1.4 非目标（明确不做，ChatGPT V1.0.11 审核红线）

- ❌ **不做 callable source introspection**：`inspect.getsource` / `inspect.getsourcelines` / AST 解析 / `dis` 反汇编
- ❌ **不做 lambda introspection**：不解析 lambda 表达式内容
- ❌ **不做 predicate expression engine**：expression parser / AST / DSL / 动态 predicate 编辑器
- ❌ **不做 predicate execution trace**：不记录每次求值的历史（那是 ConditionEval 运行时审计的职责，非静态语义）
- ❌ **不做 condition builder DSL**：不提供链式构造 predicate 的 API
- ❌ **不修改 `Condition` 类型**：`Callable[[ExecutionContext], bool]` 保持不变（ADR-0024 冻结）
- ❌ **不把 predicate 嵌入 `serialize_pipeline()` schema**：V1.0.12 不改变 V1.0.11 的 PipelineDescriptor schema（R4 stability 守护）。嵌入留待 V1.0.13 CLI presentation 时单独决策。

## 2. Decision

### 2.1 PredicateDescriptor dataclass

新增 `planner/predicate_descriptor.py`：

```python
@dataclass(frozen=True)
class PredicateDescriptor:
    """Predicate 语义描述（不可变值对象，V1.0.12）。

    回答 "What predicate is this?"，不做 "How to construct/execute it?"。
    语义由用户显式声明，不 introspect callable 源码。
    """
    name: str                 # 语义名称（识别/日志用）
    description: str = ""     # 人类可读描述（用户声明，不猜）
    subject: str = ""         # 判断目标/主语（用户声明），如 "bridge_result.success"
```

设计约束：
- `frozen=True` — 不可变值对象（与 StageDescriptor / PipelineDescriptor 一致）
- 三个字段全部是**声明式语义**，不含任何执行逻辑
- 不包含 `condition` callable 本身（descriptor 是元数据，不是可执行对象）
- 不包含 predicate 表达式/源码（红线）

### 2.2 语义来源：用户显式声明

Predicate 的语义元数据来自 **ConditionStage 构造参数**，而非 callable introspection。

新增可选构造参数（全部向后兼容，带默认值）：

```python
ConditionStage(
    condition=...,            # 既有，必填，不变
    on_true="continue",       # 既有
    on_false="continue",      # 既有
    name="condition",         # 既有（Stage 名，用于 metadata 调试）
    # V1.0.12 新增（可选）：
    predicate_name=None,        # predicate 语义名；None → fallback
    predicate_description="",   # 人类可读描述
    predicate_subject="",       # 判断目标
)
```

`predicate_name` 的 fallback 链（`describe_predicate()` 内解析）：

```python
def _resolve_predicate_name(self) -> str:
    if self.predicate_name:
        return self.predicate_name
    fn_name = getattr(self.condition, "__name__", "")
    if fn_name and fn_name != "<lambda>":
        return fn_name           # 具名函数 → 用函数名
    return "condition"           # lambda / 无名 callable → "condition"
```

关键约束：
- `getattr(condition, "__name__", "")` 是**取函数名**，不是源码 introspection（`__name__` 是函数对象的标准属性，不涉及 inspect/AST）
- lambda 的 `__name__` 是 `"<lambda>"`，被 fallback 到 `"condition"`（避免无意义展示名）
- 想要有语义的 name → 用户显式传 `predicate_name`

### 2.3 ConditionStage.describe_predicate()

在 `planner/stages/condition_stage.py` 的 `ConditionStage` 上新增：

```python
def describe_predicate(self) -> "PredicateDescriptor":
    """返回 predicate 语义描述（V1.0.12）。

    不触发 condition 求值，不 introspect callable 源码。
    """
    from planner.predicate_descriptor import PredicateDescriptor
    return PredicateDescriptor(
        name=self._resolve_predicate_name(),
        description=self.predicate_description,
        subject=self.predicate_subject,
    )
```

约束：
- **不触发 condition 求值**（无副作用，与 `pipeline.describe()` 的 no-side-effect 原则一致）
- **不调用 inspect**（红线守护，测试强制验证）

### 2.4 serialize_predicate() canonical function

在 `planner/metadata_serialization.py` 新增：

```python
def serialize_predicate(pd: PredicateDescriptor) -> Dict[str, Any]:
    """序列化 PredicateDescriptor 为 dict (V1.0.12)."""
    return {
        "name": pd.name,
        "description": pd.description,
        "subject": pd.subject,
    }
```

输出 schema：

```json
{
    "name": "on_failure",
    "description": "检查 bridge_result 是否成功",
    "subject": "bridge_result.success"
}
```

约束：
- `serialize_predicate()` 是 canonical implementation（R1 模式，与 V1.0.10 一致）
- `PredicateDescriptor.to_dict()` 是 facade（单行 delegate）
- schema 稳定测试守护 keys 不变（`name` / `description` / `subject`）

### 2.5 不嵌入 serialize_pipeline()（deferred）

V1.0.12 **不改变** `serialize_pipeline()` 的输出 schema。理由：

- V1.0.11 刚建立 PipelineDescriptor schema，R4 stability 测试守护其 keys 不变
- 若现在把 predicate 嵌进 condition stage 节点，会破坏 V1.0.11 schema 稳定性
- Predicate 语义通过独立的 `ConditionStage.describe_predicate()` + `serialize_predicate()` 提供，消费者按需查询

嵌入决策留到 V1.0.13 CLI presentation：届时 CLI 需要「渲染 condition 节点时展示 predicate 语义」，再单独 ADR 决定如何 join（可能是在 CLI 层 join，而非改 serialize_pipeline schema）。

## 3. Consequences

### 3.1 正面

- 补齐可观测性断层：消费者现在能理解 ConditionStage「在判断什么」
- 语义靠显式声明，可靠、无 introspection 脆弱性
- 复用 V1.0.10 canonical/facade 序列化模式，架构一致
- 向后兼容：ConditionStage 现有调用零改动
- 守住红线：不滑向 expression engine

### 3.2 负面

- 语义元数据依赖用户主动声明（不声明则只有 `name` + 空 description/subject）
- 新增 `predicate_descriptor.py` 模块（模块数 +1）
- Predicate 语义与 pipeline 结构暂时分离（两处查询，非单一 join）

### 3.3 缓解

- 不声明语义时，`name` 仍有合理 fallback（具名函数名 / "condition"），desc/subject 为空是诚实的「未声明」
- 模块数 +1 与 StageDescriptor / RuntimeMetadata / PipelineDescriptor 粒度一致，可接受
- 分离是有意的：structure（pipeline）与 semantics（predicate）是正交关注点，join 留到 CLI presentation

## 4. Frozen Boundary Check

| Module | Modification | Status |
|--------|-------------|--------|
| `core/` | 0 修改 | ✅ Core Freeze (ADR-0008) |
| `router/router.py` | 0 修改 | ✅ |
| `router/health_router.py` | 0 修改 | ✅ |
| `router/score_router.py` | 0 修改 | ✅ |
| `providers/` | 0 修改 | ✅ |
| `planner/stages/condition_stage.py` | 新增可选参数 + `describe_predicate()` | ⚠️ 非冻结 |
| `planner/predicate_descriptor.py` | 新建 | ⚠️ 非冻结 |
| `planner/metadata_serialization.py` | 新增 `serialize_predicate()` | ⚠️ 非冻结 |
| `planner/stages/__init__.py` | 导出 `PredicateDescriptor` | ⚠️ 非冻结 |

说明：`planner/` 不在 Core Freeze 范围内。`ConditionStage` 的 `condition` / `on_true` / `on_false` / `name` 参数语义**不变**（仅新增可选参数），执行路径 `__call__` 零修改。

## 5. Test Plan

### 5.1 新增测试文件

`tests/test_predicate_api.py`

### 5.2 测试矩阵

| Test Class | Count | 覆盖 |
|-----------|-------|------|
| TestPredicateDescriptor | 5 | dataclass 不可变 / 字段完整性 / 默认值 / hashable / to_dict round-trip |
| TestSerializePredicate | 4 | returns_dict / schema_keys_stable / empty_description_subject / values_preserved |
| TestDescribePredicate | 6 | returns_descriptor / explicit_name / named_function_fallback / lambda_fallback / explicit_description_subject / no_evaluation_side_effect |
| TestNoIntrospection | 3 | no_inspect_getsource / no_ast_parse / no_dis_disassemble |
| TestBackwardCompat | 4 | existing_constructor_unchanged / call_behavior_unchanged / metadata_condition_eval_unchanged / pipeline_integration_unchanged |

**总计：22 tests**

### 5.3 关键测试断言

1. `PredicateDescriptor` 是 frozen（修改字段抛 `FrozenInstanceError`）
2. `serialize_predicate()` 输出 keys 恒为 `{"name", "description", "subject"}`（schema stability）
3. 显式 `predicate_name` 优先于函数名 fallback
4. 具名函数 → name = 函数名；lambda → name = "condition"
5. `describe_predicate()` **不触发** condition 求值（传入带计数器的 condition，断言计数为 0）
6. `describe_predicate()` **不调用** `inspect.getsource` / `ast.parse` / `dis.disassemble`（monkeypatch 断言未被调用）
7. ConditionStage 现有构造（不传新参数）行为不变（name / on_true / on_false / condition 语义）
8. `__call__` 执行路径零变化（condition_eval metadata 仍照旧写入）
9. 现有测试零回归（602 tests 全通过）

## 6. Implementation Plan

### 阶段 1：PredicateDescriptor
1. 创建 `planner/predicate_descriptor.py`（PredicateDescriptor dataclass + to_dict facade）

### 阶段 2：serialize_predicate()
2. 在 `planner/metadata_serialization.py` 新增 `serialize_predicate()` + 更新 `__all__`

### 阶段 3：ConditionStage 增强
3. 在 `planner/stages/condition_stage.py` 的 `ConditionStage.__init__` 新增 3 个可选参数
4. 新增 `_resolve_predicate_name()` + `describe_predicate()` 方法

### 阶段 4：导出
5. 在 `planner/stages/__init__.py` 导出 `PredicateDescriptor`

### 阶段 5：测试
6. 创建 `tests/test_predicate_api.py`（22 tests）
7. 运行全量回归测试

### 阶段 6：commit + ChatGPT code review
8. commit 实现
9. 发 ChatGPT 代码审核

## 7. Open Questions

1. **`subject` 字段命名**：`subject`（predicate 主语）vs `target`（判断目标）vs `focus`。当前选 `subject`，ChatGPT 审核时可再议。
2. **是否需要在 ConditionEval 里也回填 predicate 语义**：当前 ConditionEval（运行时审计）与 PredicateDescriptor（静态语义）分离。是否在 V1.0.13 让 CLI 把两者 join？留给 CLI presentation ADR。
3. **PredicateDescriptor 是否需要 `role` 字段**：当前只描述「判断什么」，不描述「怎么用」（continue/skip/abort 已在 ConditionStage 的 on_true/on_false）。暂不加。

## 8. Future Considerations

- **V1.0.13**：ADR-0034 CLI Introspection — 把 `pipeline.describe()` / `describe_predicate()` / `to_json()` 暴露为 CLI 命令，并决策是否 join predicate 语义到 pipeline 渲染
- **V1.1**：引入 `schema_version`（与 ADR-0031 一致 deferred）
- **V2.0**：若出现结构化 predicate（非 callable，如声明式条件对象），再评估是否引入 predicate expression 的受限子集（仍不做通用 engine）

## 9. Rejected Alternatives

### R-A: introspect callable 源码（inspect.getsource / AST）

拒绝原因：这是 ChatGPT 明确红线。Python callable 源码不可靠（lambda 无 doc、闭包捕获、字节码不可移植），且会滑向 predicate expression engine。语义必须靠用户显式声明。

### R-B: 定义 Predicate Protocol（要求 predicate 对象自带 describe()）

拒绝原因：与 ADR-0024 的 `Condition = Callable` 冲突。引入 Protocol 会要求用户把 lambda 换成带 describe() 的对象，破坏向后兼容和现有「condition 是 callable」的心智模型。PredicateDescriptor 作为独立元数据声明，而非新执行抽象。

### R-C: 把 predicate 语义直接嵌进 serialize_pipeline() 的 condition 节点

拒绝原因：破坏 V1.0.11 刚建立的 PipelineDescriptor schema（R4 stability）。structure 与 semantics 是正交关注点，join 应发生在 presentation 层（CLI），而非序列化层。

### R-D: 复用 ConditionEval 作为 predicate 描述

拒绝原因：ConditionEval 是**运行时审计**（某次求值的结果，含 timestamp/result/action），不是**静态语义**（判断什么）。两者生命周期不同：一个在每次 run 时产生，一个在构造时声明。
