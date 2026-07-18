# V1.0.8 ADR-0029 Stage Registry — ChatGPT Review Prompt

## Context

V1.0.8 Stage Registry — **ADR review** (third ADR in V1.0.8 cycle, after Runtime Access API).

**ChatGPT 9.94/10 V1.0.9 Roadmap explicit MUST:**
- "MUST: Stage Registry. registry.register() / lookup() / capabilities() / roles()"
- "Registry 是 Introspection 的基础, 没有 Registry Introspection 只能继续遍历 Stage"

This ADR covers **only Stage Registry** (Metadata Serialization + Pipeline Introspection are V1.0.9).

## Cycle So Far

- V1.0.1 ADR-0021 ExecutionPipeline (9.95/10)
- V1.0.3 ADR-0022 + 0023 Retry/Checkpoint (9.95/10)
- V1.0.4 ADR-0024 ConditionStage (9.9/10 + 9.95/10)
- V1.0.5 ADR-0025 PipelineHooks (9.9/10 + 9.93/10)
- V1.0.6 ADR-0026 StageDescriptor (9.94/10 + 9.95/10) — Accepted
- V1.0.7 ADR-0027 RuntimeMetadata (9.85/10 + 9.88/10) — Accepted
- V1.0.8 ADR-0028 Metadata Access API (9.91/10 + 9.94/10) — Accepted
- **V1.0.8 ADR-0029 Stage Registry (DRAFT, a09cf7e) — review pending**

## What to Review (V1.0.8 ADR-0029)

**File:** `docs/adr/0029-stage-registry.md` (~770 lines, Draft)

**Core Proposal:**

```python
class StageRegistry:
    """Stage 注册中心 + 索引 + 查询 API (V1.0.8, ADR-0029)."""

    # 1. 注册 / 注销
    def register(self, stage: Stage, *, replace: bool = False) -> None
    def unregister(self, name: str) -> Optional[Stage]
    def clear(self) -> None

    # 2. 查询
    def lookup(self, name: str) -> Optional[Stage]
    def by_role(self, role: str) -> List[Stage]
    def by_capability(self, capability: str) -> List[Stage]
    def all(self) -> List[Stage]
    def roles(self) -> Set[str]
    def capabilities(self) -> Set[str]

    # 3. Python 容器语义
    def __contains__(self, name) -> bool
    def __len__(self) -> int
    def __iter__(self)
    def __getitem__(self, name) -> Stage

    # 4. Default registry singleton
def default_registry() -> StageRegistry:
    """进程级 singleton, auto-register 5 built-in Stage"""

    # 5. Default pipeline factory
def default_pipeline(*, registry: Optional[StageRegistry] = None) -> Pipeline:
    """用 registry 构造 default Pipeline, role 顺序: stage → metric → checkpoint → condition"""
```

**Key Design Decisions:**

1. **O(1) 索引** for `by_role()` / `by_capability()` (预构建 dict + set)
2. **Default singleton** via `_DEFAULT_REGISTRY` (auto-register 5 built-in)
3. **Default pipeline 工厂** 按 role 固定顺序: stage → metric → checkpoint → condition
4. **register 默认 raise** on duplicate name (replace=True 显式)
5. **clear() 不影响 default** (instance method, default 是不同 instance)
6. **第三方友好**: 显式 `register(MyPluginStage())`
7. **100% 向后兼容** V1.0.1-V1.0.7 (所有现有 Pipeline 构造保留)
8. **Core Freeze** 保持 (不改 core/, router/, providers/)

## 8 Questions for Review

1. **8 核心方法完整？** register / unregister / lookup / by_role / by_capability / all / roles / capabilities。是否需要 `by_owner()` / `by_version()` / `experimental()` / `find_by_predicate(callable)` 等？

2. **Default registry singleton 行为合理？** `_DEFAULT_REGISTRY` 全局, 首次调用 auto-register built-in。是否应用 `functools.lru_cache`？是否需要 `reset_default_registry()` 测试 helper（用户 V1.0.7 9.88/10 喜欢 "test-friendly"）？

3. **Default pipeline role 顺序合理？** stage → metric → checkpoint → condition。V1.0.x 实践验证。是否需要 `default_pipeline(role_set=("stage", "metric"))` 构造变体？V1.0.9 评估？

4. **register 默认 raise vs replace 合理？** `replace=False` 默认。是否应改成 `replace=True` 默认（宽容）？还是分开 `register()` raise + `register_or_replace()` 显式？

5. **Clear 不影响 default 行为？** `default_registry().clear()` 不影响 built-in (因为 clear 是 instance method)。这是 bug 还是 feature？ChatGPT V1.0.7 9.88/10 强调"test-friendly"，是否需要 `default_registry().clear_with_builtins_reset()`？

6. **第三方 Stage 集成方式？** 显式 `register()` 是 V1.0.8 唯一方式。是否需要 `entry_points` auto-discovery (V1.0.9)？是否需要 `@register_stage` decorator (V1.0.9)？

7. **与 ADR-0028 Metadata Access API 协同？** Registry 不感知 RuntimeMetadata (聚焦 Stage 自身)。是否应加组合 API 如 `registry.find_stages_for_runtime_state(runtime)`？还是保持 Registry 只管 Stage 自身 (V1.0.9 Pipeline Introspection 再组合)？

8. **V1.0.8 范围聚焦？** 采纳 ChatGPT 9.91/10 Q7 "小 ADR" 建议, 本 ADR 只做 Registry。Pipeline Introspection / Metadata Serialization / Predicate API 全部 V1.0.9。scope 是否合理？

## Expected Score

**9.5+/10** (V1.0.8 ADR-0028 是 9.91/10, 本 ADR 范围相似)

## Test Plan (V1.0.8)

- 25+ StageRegistry 核心测试
- 8+ Default registry 测试
- 5+ Default pipeline 工厂测试
- 3+ 第三方 Stage 集成测试
- 总计：41+ 新增测试 (V1.0.8 共 380+ tests)

## Key Files

- **ADR:** `docs/adr/0029-stage-registry.md` (~770 lines, Draft, a09cf7e)
- **V1.0.6 StageDescriptor (dependency):** `planner/stage_descriptor.py` (~140 lines)
- **V1.0.7 RuntimeMetadata (peer):** `planner/runtime_metadata.py` (350 lines)
- **V1.0.8 Metadata Access API (peer):** `planner/runtime_metadata.py` (+156 lines)

## Important Constraints

- ✅ **Zero breaking changes** to V1.0.1-V1.0.7
- ✅ **Pipeline 行为完全不变** (Registry 仅提供 Stage 来源)
- ✅ **第三方 Stage / Hook 不感知 V1.0.8**
- ✅ **Core Freeze maintained** (only `planner/` extension)
- ✅ **不**改 StageDescriptor (V1.0.6 稳定)
- ✅ **不**改 RuntimeMetadata / Access API (V1.0.7-V1.0.8 稳定)
