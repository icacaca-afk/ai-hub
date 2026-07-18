# V1.0.6 StageDescriptor — ChatGPT Code Review (9.95/10 APPROVED)

**Date:** 2026-07-18
**Reviewer:** ChatGPT (external)
**Code Reviewed:** Commit `d8f8c6d` (V1.0.6 StageDescriptor implementation)
**Verdict:** **APPROVED — Production Ready, ready to merge**

---

## 1. Score

**9.95 / 10** (APPROVED, 可合并)

> "从你提供的 ADR 演进来看，V1.0.x 已经形成了比较清晰的一条演进主线: ExecutionPipeline → Retry → Checkpoint → Condition → Hooks → StageDescriptor. 这几步之间没有出现明显的架构回退, StageDescriptor 也确实解决了 V1.0.4 中唯一让我会担心的设计债（stage.name == "checkpoint"）。"

> "这是一个成熟、可发布的实现。相比 V1.0.5，V1.0.6 最重要的价值不是增加功能，而是消除了基于字符串和 duck typing 的 Pipeline 耦合，把 Stage 的行为能力提升为显式元数据（StageDescriptor），为后续 Runtime Metadata、Stage Registry 和插件体系打下了稳定基础。"

## 2. Sub-Scores

| 维度 | 分数 |
|------|------|
| Architecture | 10/10 |
| API Stability | 9.9/10 |
| Runtime Contract | 10/10 |
| Backward Compatibility | 10/10 |
| Test Strategy | 9.9/10 |
| Extensibility | 10/10 |
| **Overall** | **9.95/10** |

## 3. Q&A Response

### Q1: StageDescriptor 结构 → 保持 flat dataclass

> "我不会拆 Metadata 子对象。原因: 如果拆 descriptor.metadata.owner / descriptor.behavior.idempotent, API 会明显复杂。V1.x 不值得。"

**优先级：** Adopt。保持 flat dataclass。

### Q2: FrozenSet → 正确

> "Descriptor 已经 @dataclass(frozen=True), 那么 FrozenSet 比 Set 一致。否则 descriptor 可 hash, descriptor.capabilities 却 mutable, 会出现语义冲突。"
> **建议：** 增加辅助构造（`StageDescriptor.with_capabilities(...)` 或内部 `frozenset(...)` 自动转换）。**非阻塞**。

**优先级：** Adopt (FrozenSet 保留)。辅助构造 V2 评估。

### Q3: Protocol → 正确

> "Stage 实际上就是 duck typing, 真正需要的是 callable(ctx) + descriptor, 而不是继承。Protocol 非常符合 Python 风格。"
> **建议：** 加 `def is_stage(obj) -> TypeGuard[Stage]` 替代 `isinstance(..., Stage)`。**V2 优化**。

**优先级：** Defer。V2 加 TypeGuard。

### Q4: Lazy Import → **改用 TYPE_CHECKING** ⭐

> "这是我唯一建议调整的地方。现在 pipeline.py 用 lazy import StageDescriptor, 说明有循环引用。真正应该解决的是 ExecutionContext 不要进入 stage_descriptor.py。推荐 from typing import TYPE_CHECKING。"

**优先级：** **非阻塞，Adopt**。改用 `TYPE_CHECKING` 消除循环依赖。

### Q5: Hook TypeError fallback → **改用 inspect.signature** ⭐

> "如果 Hook 内部 raise TypeError(...) 也会被误判。更稳的方式: inspect.signature() 初始化时缓存 supports_descriptor=True, 之后 if support: ... 这样 Pipeline 每次 fire 都不用 TypeError。"
> "Pythonic but fragile"

**优先级：** **非阻塞，Adopt**。改用 `inspect.signature` 缓存兼容性。

### Q6: always_run_after_stop → 保持

> "Behavior > Taxonomy。这是本次 ADR 最大的优点。任何 Stage: CleanupStage / AuditStage / TelemetryStage 都可以 always_run_after_stop=True, Pipeline 根本不用知道它是谁。典型 Open/Closed。"

**优先级：** Adopt。当前设计正确。

### Q7: Built-in Stage migration → 完成

> "Route / Retry / Metrics / Condition / Checkpoint 全部都有 descriptor。这就是我之前 ADR 中建议的方案。千万不要 factory 猜测 (hasattr(stage, 'store'))。当前实现是正确的。"

**优先级：** Adopt。Critical 已采纳。

### Q8: V1.0.4 兼容性 → 保持

> "Checkpoint 自己声明 always_run_after_stop=True, Pipeline 用 descriptor.always_run_after_stop, 所以 ctx.stop=True → Checkpoint 仍执行。V1.0.4 Runtime Contract 没被破坏。这是 ADR-0026 最大成功点。"

**优先级：** Adopt。已验证。

### Q9: 测试覆盖 → 加 2 个 ⭐

**建议 1：** `assert stage.descriptor is stage.descriptor` — Descriptor 是常量, 不是每次 new。
**建议 2：** Unknown third-party stage — `class ThirdParty: name="abc"; def __call__(...)` 验证 get_descriptor() 默认 descriptor + Pipeline 正常运行。

**优先级：** 非阻塞，Adopt。

### Q10: V1.0.7 Runtime Metadata Schema → 无冲突

> "StageDescriptor 与 RuntimeMetadata 没冲突。Descriptor 答 Stage 自身, Metadata 答 ExecutionContext 当前运行。两个维度不同。没有命名空间冲突。ADR-0027 可以直接继续。"

**优先级：** Adopt。V1.0.7 推进。

## 4. Adopt / Defer Summary

| 建议 | 优先级 | 状态 |
|------|--------|------|
| 保持 StageDescriptor flat dataclass | Critical | 当前设计正确 |
| 保持 FrozenSet | Critical | 当前设计正确 |
| 保持 Protocol | Critical | 当前设计正确 |
| 所有 built-in Stage 显式 descriptor | Critical | 已完成 |
| 保持 always_run_after_stop 行为信号 | Critical | 当前设计正确 |
| **改用 TYPE_CHECKING 消除 lazy import** | 非阻塞 | **采纳 (本 commit)** |
| **Hook 改用 inspect.signature 缓存** | 非阻塞 | **采纳 (本 commit)** |
| **加 Descriptor identity 测试** | 非阻塞 | **采纳 (本 commit)** |
| **加 third-party stage 兼容性测试** | 非阻塞 | **采纳 (本 commit)** |
| TypeGuard is_stage() | Defer | V2 |
| Metadata 子对象 | Defer | V2 |
| Enum Role | Defer | V2 |

## 5. V1.0.7 ADR-0027 路线建议 (ChatGPT)

> "下一步不要继续增加新的 Stage, 而应开始稳定运行时元数据模型。"

1. **Runtime Metadata Schema** — 统一 ctx.metadata 命名空间 (condition_eval / server_metrics / retry)
2. **Stage Registry** — 基于 StageDescriptor 建立注册与发现机制
3. **Metadata Validation** — schema 校验或约定

## 6. Code-Level Adjustments (本 commit 采纳)

### 6.1 改用 TYPE_CHECKING 消除循环依赖

```python
# planner/stage_descriptor.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from planner.pipeline import ExecutionContext

@runtime_checkable
class Stage(Protocol):
    descriptor: "StageDescriptor"
    def __call__(self, ctx: "ExecutionContext") -> "ExecutionContext": ...
```

### 6.2 Hook 改用 inspect.signature 缓存

```python
# planner/hooks.py
import inspect

def _supports_descriptor(hook) -> bool:
    """检查 hook 是否接受 descriptor 关键字参数."""
    try:
        sig = inspect.signature(hook)
        return "descriptor" in sig.parameters
    except (ValueError, TypeError):
        return False

class PipelineHooks:
    def __init__(self, ...):
        # 缓存 supports_descriptor
        self._before_stage_supports = [_supports_descriptor(h) for h in (before_stage or [])]
        ...

    def fire_before_stage(self, ctx, stage_name, descriptor=None):
        for hook, supports in zip(self.before_stage, self._before_stage_supports):
            try:
                if supports:
                    hook(ctx, stage_name, descriptor=descriptor)
                else:
                    hook(ctx, stage_name)
            except Exception as e:
                logger.warning(...)
```

### 6.3 加 2 项测试

```python
# test_stage_descriptor.py
def test_descriptor_identity(self):
    """Descriptor 是常量, 同一 stage 多次访问返回同一对象."""
    stage = CheckpointStage(InMemoryStore())
    assert stage.descriptor is stage.descriptor  # 同一对象

def test_third_party_stage_compatibility(self):
    """Unknown third-party Stage 无 descriptor, 接收默认 Descriptor."""
    class ThirdParty:
        name = "abc"
        def __call__(self, ctx): return ctx
    
    d = get_descriptor(ThirdParty())
    assert d.name == "abc"
    assert d.always_run_after_stop is False  # 兜底不暗示语义
```

## 7. 总体结论

> **评分：9.95 / 10**
> **结论：APPROVED，建议合并。**
>
> 这是一个成熟、可发布的实现。相比 V1.0.5，V1.0.6 最重要的价值不是增加功能，而是消除了基于字符串和 duck typing 的 Pipeline 耦合，把 Stage 的行为能力提升为显式元数据（StageDescriptor），为后续 Runtime Metadata、Stage Registry 和插件体系打下了稳定基础。

## 8. V1.0.6 状态

**本 commit (V1.0.6 Accepted) 采纳：**

**2 项非阻塞代码调整：**
- ✅ 改用 TYPE_CHECKING 消除 lazy import 循环依赖
- ✅ Hook 改用 inspect.signature 缓存 supports_descriptor

**2 项非阻塞测试补充：**
- ✅ Descriptor identity (同一对象)
- ✅ Third-party stage 兼容性

**保持不变：**
- ✅ StageDescriptor flat dataclass
- ✅ FrozenSet[str] capabilities
- ✅ Protocol (runtime_checkable)
- ✅ always_run_after_stop 单一行为信号
- ✅ 所有 built-in Stage 显式 descriptor
- ✅ V1.0.4 Runtime Contract 兼容性

**V1.0.7 推进：** ADR-0027 Runtime Metadata Schema 统一（无冲突）。

**V2 路线：** TypeGuard is_stage() / Metadata 子对象 / Enum Role。
