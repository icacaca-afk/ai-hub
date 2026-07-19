# ADR-0029 Code-Level ChatGPT Review Summary

- **审核目标**: V1.0.8 Stage Registry 代码实施 (commit 6fb4362)
- **审核时间**: 2026-07-19
- **审核 prompt**: `docs/reviews/0029-code-chatgpt-review-prompt.md` (~10.8 KB)
- **审核 raw 回复**: `docs/reviews/0029-code-chatgpt-review-raw.txt` (~7.7 KB)
- **总评分**: **9.72 / 10 APPROVED** ✅
- **状态**: Approved with ADR-0029 Rev1 修订要求

---

## 审核评分明细

| 维度 | 分数 |
|------|------|
| 架构方向 | 10 / 10 |
| ADR 一致性 | 9 / 10 |
| Runtime 注入设计 | 10 / 10 |
| Registry 抽象 | 10 / 10 |
| 测试质量 | 9.7 / 10 |
| API 稳定性 | 10 / 10 |
| 长期扩展性 | 9.8 / 10 |
| **总分** | **9.72 / 10** |

---

## 审核结论

> 代码方向正确，ADR 需要回写。
> 不应该反过来修改代码迎合 ADR。
>
> V1.0.8 的核心价值是把 Stage 从"硬编码 Pipeline"提升为"可发现、可组合、可扩展注册系统"。
> 这个目标已经达成。

---

## 8 个审核维度结论

### 1. ADR Deviation: `default_pipeline(router, *, store, registry)` — 10/10

ChatGPT 确认代码修正正确。原 ADR §2.3 `default_pipeline(*, registry=None)` 存在 3 个隐藏错误：
- **错误 1**: ADR 假设 `Pipeline(stages=stages)` 存在，实际是 `ExecutionPipeline(router, pre_bridge_stages, post_bridge_stages)`
- **错误 2**: `RouteStage()` 零参无法工作，实际需要 `RouteStage(router)`
- **错误 3**: `CheckpointStage()` 零参无法工作，实际需要 `CheckpointStage(store)`

**修正方向（采纳）**:
> Registry stores discoverable Stage descriptors and prototype instances.
> Runtime dependencies must be injected by pipeline factories.

### 2. Stub dependencies 合理性 — 9.5/10

ChatGPT 确认 stub deps (`router=None`, `_NullStore()`) 是正确方向 — Registry 仅保存 Stage identity / role / capability / metadata，不保证 runnable。

**风险**: 用户 `registry.lookup("route").execute(...)` 会得到 `AttributeError: router is None`。

**建议（采纳）**: 为 `RouteStage` / `CheckpointStage` 增加 misuse guard，将 `NoneType error` 升级为 `Architecture misuse error`。

### 3. Registry instance ≠ Pipeline instance — 10/10

ChatGPT 确认这是正确设计（类似 Spring BeanDefinition vs Bean Instance）：
- Registry = BeanDefinition（discovery metadata）
- Pipeline = Bean Instance（runtime wiring）

`registry.lookup("route") != pipeline.route_stage` 完全合理。

### 4. `store=None` 跳过 checkpoint — 9.8/10

ChatGPT 支持 `store=None => no checkpoint` 设计，符合 Registry 哲学：
> capability available ≠ capability mandatory

**ADR 建议**: 明确 `CheckpointStage is optional runtime capability. Absence of store disables checkpointing.`

### 5. RetryStage registered but NOT in DEFAULT_ORDER — 10/10

ChatGPT 确认正确。两个概念必须分离：
- **discovery order**: "系统有什么"
- **execution order**: "默认运行什么"

如果所有注册的 Stage 都进 DEFAULT_ORDER，最终 DEFAULT_ORDER 会变成"垃圾桶"。

### 6. 两个 `default_pipeline` 命名冲突 — 9.0/10

**唯一明显架构债**：
- `planner.pipeline.default_pipeline` (V1.0.4)
- `planner.stage_registry.default_pipeline` (V1.0.8)

ChatGPT 短期可接受（无 breaking change），V1.1 前建议处理：
- 旧 API 改文档别名为 `legacy_default_pipeline`，或
- 新增 `planner.pipeline.create_pipeline`

**决策**: V1.0.8 不改，V1.1 评估。

### 7. `_NullStore` 私有 — 10/10

ChatGPT 确认 `_NullStore` 私有正确。它不是业务对象，只是 implementation adapter。公开 `NullStore` 反而污染 API。

### 8. 测试覆盖 — 9.7/10

62 个测试覆盖：register / replace / unregister / index / capability / role / singleton / factory / DI / store toggle。

**缺少（V1.1 处理）**:
1. mutation during iteration — `for stage in registry: registry.unregister(stage.name)`
2. thread safety — 未来 MCP server / WebUI 多线程访问时考虑 `threading.RLock`
3. property test — `register / unregister / register` 后 `index == storage` 不变量

---

## ADR-0029 Rev1 必修订项（3 项）

ChatGPT 要求在 merge/tag 前修订 ADR-0029：

### 修订 1: Stage Registry 定义

增加：
> Registry stores discoverable Stage definitions, not guaranteed executable runtime instances.

### 修订 2: `default_pipeline` 签名

```python
# 旧 (ADR §2.3 原版):
def default_pipeline(*, registry: Optional[StageRegistry] = None) -> Pipeline:
    ...
    return Pipeline(stages=stages)

# 新 (Rev1):
def default_pipeline(
    router: Any,
    *,
    store: Any = None,
    registry: Optional[StageRegistry] = None,
) -> ExecutionPipeline:
    """Registry 仅 discovery, Pipeline factory 注入 runtime deps."""
```

### 修订 3: 三阶段 Runtime Dependency Injection 模型

新增：
- **Registry phase**: Stage discovery（按 name/role/capability 索引）
- **Factory phase**: Runtime dependency injection（`default_pipeline(router, store)`）
- **Execution phase**: Pipeline execution（`ExecutionPipeline.__call__`）

---

## 代码层采纳项（1 项可选 + 0 项必改）

### 可选采纳: RouteStage / CheckpointStage misuse guard

ChatGPT 建议在 `RouteStage.__call__` / `CheckpointStage.__call__` 增加保护：

```python
class RouteStage:
    def __call__(self, ctx):
        if self.router is None:
            raise RuntimeError(
                "RouteStage from registry is discovery-only. "
                "Use default_pipeline() for execution."
            )
        ...
```

**决策**: 采纳（小改动，将 `NoneType error` 升级为 `Architecture misuse error`，提升 DX）。

---

## 下一步路线建议（ChatGPT）

```
V1.0.8 fixup
  ↓
ADR-0029 Rev1
  ↓
tag v1.0.8
  ↓
V1.0.9 Stage Lifecycle Hooks
   ↓
   before_execute
   after_execute
   on_error
```

> Stage Registry 这一层打稳后，后面的 Workflow Runtime / DAG Executor 会明显容易很多。

**注**: V1.0.9 实际路线图按用户先前规划：ADR-0030 Registry Introspection (MUST ①) + ADR-0031 Metadata Serialization (MUST ②)。Stage Lifecycle Hooks 留待 V1.0.10+ 评估。

---

## 原始审核回复

完整 ChatGPT 回复见 `docs/reviews/0029-code-chatgpt-review-raw.txt`。
