# V1.0.11 Pipeline Introspection — ChatGPT 代码审核记录

- **日期**: 2026-08-13
- **审核对象**: commit `4e91759` (V1.0.11 Pipeline Introspection 实现)
- **评分**: **9.8/10 ✅ APPROVED / implementation-ready / release-ready**
- **上一轮**: ADR 审核 9.4/10 Conditional Approve（3 个 P0）

## 结论

3 个 P0 已全部关闭，V1.0.11 架构可以冻结。评分从 9.4/10 提升为 9.8/10 APPROVED。

## 逐项结论（5 个确认问题）

| 问题 | 结论 |
|------|------|
| 1. PipelineDescriptor 是 serialize_pipeline 唯一入参 | ✅ 应冻结为 architecture invariant |
| 2. role 基于 exact 类型名 | ✅ 当前批准；subclass/同名类为 P1 hardening |
| 3. Bridge virtual node 放 stages | ✅ 批准，符合 graph closure 意图 |
| 4. 45 tests 是否充分 | ✅ 充分；可再加 topology invariant + subclass policy 两个增强测试 |
| 5. V1.0.12 下一步 | ✅ 继续 Predicate API / ADR-0033 |

## 关键批准点

1. **单向转换链冻结为 invariant**（更强于普通 ADR decision）：
   ```
   ExecutionPipeline → describe() → PipelineDescriptor → serialize_pipeline() → dict → to_json() → JSON
   ```
   `No serialization function may introspect ExecutionPipeline directly.`

2. **graph closure 达成**：`∀ edge.from ∈ node_ids ∧ ∀ edge.to ∈ node_ids`，消费者不再需要 `create_fake_node()` 特殊逻辑。

3. **role 基于类型名**（`type(stage).__name__`）优于基于 `stage.name`，`custom_name_does_not_change_role` 已锁住。

4. **neither 空结构**：`bridge` + `edges=[]`，即使无 Stage 仍表达 execution boundary exists。

5. **has_hooks = hooks.enabled** 语义批准（实际配置了至少一个 Hook，非容器存在性）。

## P1 硬化项（不阻塞 V1.0.11）

1. **index=-1 语义文档化**：`index` 是 within-segment（pre/post 各自从 0 起），不是 global order；bridge 用 -1 sentinel。ADR 需明确，否则 `sorted(stages, key=lambda x: x["index"])` 会得到错误顺序。

2. **exact type-name 对 subclass/同名类的边界**：
   - `class MyRouteStage(RouteStage)` → `type().__name__=="MyRouteStage"` → unknown（反直觉）
   - 无关同名类 `RouteStage` → router（可能 false positive）
   - 未来硬化建议：`for cls in type(stage).__mro__: role = _STAGE_ROLE_MAP.get(cls.__name__)`

## 两个增强测试建议（非 blocker）

1. **topology invariant 参数化测试**：
   - `node_count == N + 1`（+bridge）
   - `edge_count == N`（= node_count - 1）
   - 每个 edge endpoint 存在、无 self-edge、无 duplicate edge、bridge 最多一入一出

2. **role 分类边界**：`DerivedRouteStage(RouteStage)` 期望 router 还是 unknown，需冻结行为。

## 重要声明（ChatGPT 本人声明）

ChatGPT 明确说明：**未拿到 `4e91759` 实际源码文件**，结论是对「实现契约 + 测试报告」的批准，不是逐行验证 commit 后的代码签字。需在本地 line-level 复核 `hooks.enabled` 是否真的等价于「至少一个 active/configured hook」（而非 hook subsystem globally enabled）。

## V1.0.12 路线建议

- **进入 ADR-0033 Predicate API**，不要直接跳 CLI。
- 核心原则：**不做 Predicate expression engine**，只回答 "What predicate is this?"，不做 "How to construct/edit/execute arbitrary predicates?"
- ❌ 禁止：expression parser / AST / lambda introspection / dynamic predicate editor / predicate execution trace / condition builder DSL
- 继续沿 metadata 链：`Predicate → describe() → PredicateDescriptor → canonical serializer → dict`
- 顺序：V1.0.11 structure → V1.0.12 predicate semantics → V1.0.13 CLI presentation
