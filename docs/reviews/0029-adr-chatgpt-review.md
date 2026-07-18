# V1.0.8 ADR-0029 Stage Registry — ChatGPT Review

**ADR File:** `docs/adr/0029-stage-registry.md` (Draft, commit a09cf7e)
**Review Date:** 2026-07-18
**Reviewer:** ChatGPT (external)
**Raw Reply:** `0029-adr-chatgpt-review-raw.txt`
**Verdict:** ✅ **APPROVED 9.93/10** (0 Blocking Issues)

---

## 总评分

| 维度 | 分数 | 评价 |
|------|------|------|
| 架构定位 | **10.0** | Runtime 三层 (Descriptor → Registry → Pipeline) 形成 |
| API 设计 | **9.9** | 8 核心方法, 职责清晰 |
| StageDescriptor 一致性 | **10.0** | 完整复用 V1.0.6 descriptor |
| Pipeline 解耦 | **10.0** | Pipeline 只认识 Registry, Registry 只认识 Descriptor |
| 可扩展性 | **9.8** | V1.0.9 Introspection / V2 Plugin Discovery 留好接口 |
| 向后兼容 | **10.0** | 100% 兼容 V1.0.1-V1.0.7 |
| 测试设计 | **9.9** | 41+ tests 覆盖 |
| **Overall** | **9.93** | **APPROVED** — Runtime 基础设施最后一块大拼图 |

## 结论

> "ADR-0029 解决的是：'Stage 怎么被组织和发现'"
> "这是 Runtime 基础设施最后一块比较大的拼图"
> "Runtime 终于开始形成完整三层: Descriptor → Registry → Pipeline"
> "StageRegistry 管 Stage、RuntimeMetadata 管运行态、ExecutionPipeline 管执行流程, 三者没有相互侵入"
> "如果继续保持这种分层, 后续加入 Registry Introspection、Metadata Serialization 和 Pipeline Describe 等能力时, 不需要回头修改现有架构"

---

## 核心评价 (Q1-Q8)

### Q1 Registry API 完整？ — **8 核心方法足够**

> "已经够了。我反而不建议现在加入 by_owner() / by_version() / experimental()"
> "Registry 的职责应该是：找 Stage。而不是：查询所有 Metadata"
> "现在保持：最小 API。很好"

**采纳：** 不加 by_owner / by_version / experimental (V1.0.8 范围聚焦)

### Q2 Default Registry Singleton — **T1 Non-blocking 必须加**

> "目前 _DEFAULT_REGISTRY 没有问题。但是建议增加：reset_default_registry()"
> "不是 Runtime 用。而是测试"
> "例如：register(plugin) / ... / tearDown() / reset_default_registry()"
> "否则：Singleton 很容易污染后续 Test"
> "这是我唯一建议：V1.0.8 就加"
> "属于 Non-blocking"

**采纳 T1：** `reset_default_registry()` 测试 helper

### Q3 Pipeline Role Ordering — **Q3 重构建议**

> "ADR 明确一点：不要写死名字。而写：默认 Registry 提供默认顺序"
> "Registry.default_order() / Pipeline: registry.pipeline_order()"
> "以后：新增 trace / cache / observer, Pipeline 不用改"

**采纳：** `StageRegistry.default_order()` 暴露顺序, Pipeline 走 registry（V1.0.8 实施时改）

### Q4 replace=False — **保持**

> "现在设计很好。默认 register() 重复 Raise"
> "Python dict / logging / argparse 都喜欢的 Fail Fast"
> "比 register_or_replace() 更 Python。保持即可"

**采纳：** 保持 replace=False 默认

### Q5 clear() — **职责分离**

> "registry.clear() → 当前 Registry 清空。default_registry() → 重新初始化 Builtins"
> "不要让 clear() 自动重新注册"
> "否则 clear 语义就变复杂"
> "Registry 应该只是 Registry。Factory 负责 Builtins"
> "职责分离更清晰"

**采纳：** ADR 明确职责分离 (clear 不重注册 builtins, default_registry() 永远负责 builtins)

### Q6 Plugin Stage — **保持 V1.0.8 范围**

> "非常赞同：不要现在搞 entry_points。也不要 @register_stage"
> "Runtime 还没有 Plugin 生命周期"
> "Registry 只是 Container。不要提前变成 Plugin Manager"
> "保持 register(stage) 即可"

**采纳：** V1.0.8 仅 register(), entry_points / decorator 放 V1.0.9+ / V2

### Q7 Registry 是否知道 RuntimeMetadata — **保持解耦 (核心架构原则)**

> "这是我最希望保持的一点"
> "Registry 应该只认识 StageDescriptor (Role / Capability / Owner / Version)"
> "不要知道 ctx.runtime / condition / metrics / plan"
> "否则 Registry 开始依赖 Runtime。以后 Runtime 又依赖 Registry。形成双向依赖"
> "Registry 只负责 Stage。Runtime 只负责 ExecutionContext"
> "这是目前整个 V1.x 架构最漂亮的一点"

**采纳：** Registry 不感知 RuntimeMetadata (V1.0.8 实施时强制)

### Q8 Scope — **强烈赞成小 ADR**

> "支持拆成两个 ADR: 0028 Metadata API + 0029 Registry"
> "不要 Mega ADR"
> "以后 Review / Git History 都会清楚很多"

**采纳：** V1.0.8 = 0028 + 0029 独立 ADR

---

## 🎁 唯一建议 (V1.0.8 必须加)

### T1: `reset_default_registry()` 测试 helper

```python
def reset_default_registry() -> None:
    """重置 default registry (测试隔离用).

    关键不变量:
      - 重置后下次 default_registry() 重新 auto-register built-in
      - **不**在 Runtime 中调用 (会破坏 default registry 完整性)
      - 仅用于 pytest fixture teardown
    """
    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = None
```

### T2: `describe(name)` 返回 StageDescriptor

```python
def describe(self, name: str) -> Optional[StageDescriptor]:
    """返回 Stage 的 StageDescriptor (不返回 Stage 实例).

    Use case:
      - CLI: `registry.describe("checkpoint")` 打印 descriptor 信息
      - Documentation: 自动生成 Stage catalog
      - Inspection: 调试时不需要 Stage 实例, 仅 metadata

    Args:
        name: Stage name

    Returns:
        StageDescriptor 或 None (未找到)
    """
    stage = self._stages.get(name)
    if stage is None:
        return None
    return get_descriptor(stage)
```

> "registry.describe(name) 会非常自然"
> "例如: registry.describe('checkpoint') → StageDescriptor(...)"
> "以后 CLI 直接打印 Descriptor"

**采纳 T1 + T2：** V1.0.8 实施时加

---

## Q3 重构: Registry.default_order() 暴露顺序

```python
# StageRegistry class
DEFAULT_ORDER: Tuple[str, ...] = ("stage", "metric", "checkpoint", "condition")

def default_order(self) -> Tuple[str, ...]:
    """返回默认 Pipeline 构造顺序 (按 role).

    未来扩展 (V1.0.9+):
      - 加 trace / cache / observer 等新 role
      - Pipeline 走 registry.default_order() 而非 hardcode
    """
    return self.DEFAULT_ORDER

# default_pipeline factory
def default_pipeline(*, registry: Optional[StageRegistry] = None) -> Pipeline:
    registry = registry or default_registry()
    stages = []
    for role in registry.default_order():
        stages.extend(registry.by_role(role))
    return Pipeline(stages=stages)
```

**采纳：** V1.0.8 实施时改 (Pipeline 不再 hardcode role 顺序)

---

## Architecture 评价 (核心)

> "这一版最大的价值不是 Registry。而是 Runtime 终于开始形成完整三层"
> "Descriptor ↓ Registry ↓ Pipeline — 这是非常经典的 Runtime Architecture"
> "Stage 不用 Pipeline 认识"
> "Pipeline 只认识 Registry"
> "Registry 只认识 Descriptor"
> "这就是真正 Decouple"

**V1.x 完整架构**:
```
Layer 1 (V1.0.6): StageDescriptor — Stage 静态 metadata
Layer 2 (V1.0.8): StageRegistry    — Stage 索引 + 生命周期
Layer 3 (V1.0.1): ExecutionPipeline — Stage 调度 + 执行

Runtime:
Layer A (V1.0.7): RuntimeMetadata   — Runtime 动态 metadata
Layer B (V1.0.8): Metadata Access API — Runtime 统一访问

Future (V1.0.9+):
Layer 2+: Registry Introspection   — registry.summary() / graph()
Layer A+: Metadata Serialization   — runtime.to_dict() / from_dict()
```

---

## V1.0.9 Roadmap (采纳 ChatGPT 9.93/10)

| 优先级 | 项目 | 说明 |
|--------|------|------|
| **MUST ①** | Registry Introspection | `registry.summary()` / `describe()` / `graph()` (CLI 用) |
| **MUST ②** | Metadata Serialization | `runtime.to_dict()` / `from_dict()` |
| **SHOULD** | Pipeline Describe | `pipeline.describe()` / `plan()` / `stages()` (依赖 Registry) |
| **LATER V1.0.9+** | Plugin Discovery | `entry_points` / `@register_stage` decorator / dynamic loading |
| **LATER V2** | Schema Validation | Pydantic / JSON Schema |

---

## Adopt / Defer 总结

| 建议 | 结论 | 优先级 |
|------|------|--------|
| Registry 独立 ADR | ✅ Adopt (DRAFT) | — |
| register / lookup API | ✅ Adopt (DRAFT) | — |
| role / capability 查询 | ✅ Adopt (DRAFT) | — |
| default_registry() | ✅ Adopt (DRAFT) | — |
| replace=False 默认 | ✅ Adopt (DRAFT) | — |
| Pipeline 使用 Registry | ✅ Adopt (DRAFT) | — |
| `reset_default_registry()` | 🟡 Adopt T1 (Non-blocking) | 实施阶段 |
| `describe(name)` → StageDescriptor | 🟡 Adopt T2 (Non-blocking) | 实施阶段 |
| `default_order()` 暴露 | 🟡 Adopt (Q3 重构) | 实施阶段 |
| clear 不重注册 builtins | 🟡 Adopt (Q5 职责分离) | ADR 明确 |
| Registry 不感知 RuntimeMetadata | ✅ Adopt (Q7 核心) | 实施时强制 |
| by_owner / by_version | ❌ Reject (Q1 过度) | — |
| Entry Points auto-discovery | 🟡 V1.x 后期/V2 | Defer |
| @register_stage decorator | 🟡 V1.0.9+ | Defer |
| Registry Introspection | 🟡 V1.0.9 MUST ① | Defer |
| Metadata Serialization | 🟡 V1.0.9 MUST ② | Defer |
| Schema Validation | 🟡 V2 | Defer |

---

## V1.0.8 实施下一步

1. ✅ V1.0.8 ADR-0029 Accepted (9.93/10)
2. 🔜 V1.0.8 实施：
   - 8 核心方法 + 索引管理
   - 2 新增方法 (T1 reset_default_registry + T2 describe)
   - default_order() 暴露
   - 41+ tests
3. 🔜 V1.0.8 Stage Registry 代码层 ChatGPT 审核（期望 9.5+/10）
4. 🔜 V1.0.8 Final Accepted
5. 🔜 启动 V1.0.9 ADR-0030 Registry Introspection (ChatGPT 路线图 MUST ①)
6. 🔜 启动 V1.0.9 ADR-0031 Metadata Serialization (ChatGPT 路线图 MUST ②)
7. 🔜 V1.0.9 Pipeline Describe (SHOULD)
