# AI Hub — Stage Registry Tests (V1.0.8, ADR-0029 Accepted 9.93/10)
#
# 测试 StageRegistry 核心能力 + default_registry singleton + 第三方 Stage 集成.
# 覆盖 ADR §6.1 (StageRegistry core) + §6.2 (Default Registry) + §6.4 (Third-party):
#   - 8 核心方法: register / unregister / lookup / by_role / by_capability / all / roles / capabilities
#   - Python 容器语义: __contains__ / __len__ / __iter__ / __getitem__
#   - T2: describe(name) 返回 StageDescriptor
#   - Q3: default_order() 暴露顺序
#   - Q5 职责分离: clear() 不重注册 builtins
#   - T1: reset_default_registry() 测试 helper
#   - 第三方 Stage register / by_capability / replace=False raises

from __future__ import annotations

import pytest

from planner.stage_descriptor import StageDescriptor, get_descriptor
from planner.stage_registry import (
    StageRegistry,
    default_registry,
    reset_default_registry,
)


# ─────────────────────────────────────────────────────────────
# Helpers — Stub Stage factory (zero-arg, for testing)
# ─────────────────────────────────────────────────────────────

def _make_stub(
    name: str,
    role: str = "stage",
    capabilities=frozenset(),  # type: ignore
):
    """Create a stub Stage instance with given descriptor fields.

    Each call creates a NEW class (so descriptor is unique per instance).
    """

    class _StubStage:
        descriptor = StageDescriptor(
            name=name, role=role, capabilities=capabilities
        )

        def __call__(self, ctx):
            return ctx

    return _StubStage()


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def empty_registry():
    """Fresh empty StageRegistry (no built-in, test isolation)."""
    return StageRegistry()


@pytest.fixture
def clean_default():
    """Reset default_registry before + after test (singleton isolation)."""
    reset_default_registry()
    yield
    reset_default_registry()


# ─────────────────────────────────────────────────────────────
# §6.1 TestStageRegistryCore — 8 核心方法 + 容器语义 (27 tests)
# ─────────────────────────────────────────────────────────────

class TestStageRegistryEmpty:
    """空 Registry 初始 state."""

    def test_empty_registry_len_zero(self, empty_registry):
        assert len(empty_registry) == 0

    def test_empty_registry_all_returns_empty(self, empty_registry):
        assert empty_registry.all() == []

    def test_empty_registry_roles_empty(self, empty_registry):
        assert empty_registry.roles() == set()

    def test_empty_registry_capabilities_empty(self, empty_registry):
        assert empty_registry.capabilities() == set()


class TestStageRegistryRegister:
    """register() 核心行为."""

    def test_register_basic(self, empty_registry):
        stage = _make_stub("alpha", role="stage")
        empty_registry.register(stage)
        assert len(empty_registry) == 1
        assert empty_registry.lookup("alpha") is stage

    def test_register_replaces_when_replace_true(self, empty_registry):
        s1 = _make_stub("x", role="stage")
        s2 = _make_stub("x", role="stage")
        empty_registry.register(s1)
        empty_registry.register(s2, replace=True)
        assert len(empty_registry) == 1
        assert empty_registry.lookup("x") is s2

    def test_register_raises_on_duplicate(self, empty_registry):
        s1 = _make_stub("x", role="stage")
        s2 = _make_stub("x", role="stage")
        empty_registry.register(s1)
        with pytest.raises(KeyError, match="already registered"):
            empty_registry.register(s2)

    def test_register_multiple_different_names(self, empty_registry):
        empty_registry.register(_make_stub("a", role="stage"))
        empty_registry.register(_make_stub("b", role="metric"))
        empty_registry.register(_make_stub("c", role="checkpoint"))
        assert len(empty_registry) == 3

    def test_register_returns_none(self, empty_registry):
        stage = _make_stub("x", role="stage")
        result = empty_registry.register(stage)
        assert result is None


class TestStageRegistryUnregister:
    """unregister() 核心行为."""

    def test_unregister_existing(self, empty_registry):
        stage = _make_stub("alpha", role="stage")
        empty_registry.register(stage)
        result = empty_registry.unregister("alpha")
        assert result is stage
        assert len(empty_registry) == 0

    def test_unregister_nonexisting_returns_none(self, empty_registry):
        result = empty_registry.unregister("nonexistent")
        assert result is None

    def test_unregister_clears_indices(self, empty_registry):
        """unregister 后 by_role / by_capability 也清空."""
        stage = _make_stub("alpha", role="stage", capabilities=frozenset({"foo"}))
        empty_registry.register(stage)
        empty_registry.unregister("alpha")
        assert empty_registry.by_role("stage") == []
        assert empty_registry.by_capability("foo") == []

    def test_unregister_then_reregister(self, empty_registry):
        """注销后可重新注册同名 Stage."""
        s1 = _make_stub("x", role="stage")
        empty_registry.register(s1)
        empty_registry.unregister("x")
        s2 = _make_stub("x", role="stage")
        empty_registry.register(s2)
        assert len(empty_registry) == 1
        assert empty_registry.lookup("x") is s2


class TestStageRegistryClear:
    """clear() 核心行为 (Q5 职责分离)."""

    def test_clear_empties_registry(self, empty_registry):
        empty_registry.register(_make_stub("a", role="stage"))
        empty_registry.register(_make_stub("b", role="metric"))
        empty_registry.clear()
        assert len(empty_registry) == 0
        assert empty_registry.roles() == set()

    def test_clear_clears_capability_index(self, empty_registry):
        empty_registry.register(
            _make_stub("a", role="stage", capabilities=frozenset({"cap1"}))
        )
        empty_registry.clear()
        assert empty_registry.by_capability("cap1") == []
        assert empty_registry.capabilities() == set()


class TestStageRegistryLookup:
    """lookup() 核心行为."""

    def test_lookup_existing(self, empty_registry):
        stage = _make_stub("alpha", role="stage")
        empty_registry.register(stage)
        assert empty_registry.lookup("alpha") is stage

    def test_lookup_nonexisting_returns_none(self, empty_registry):
        assert empty_registry.lookup("nonexistent") is None


class TestStageRegistryByRole:
    """by_role() O(1) 索引查询."""

    def test_by_role_single(self, empty_registry):
        s = _make_stub("alpha", role="stage")
        empty_registry.register(s)
        result = empty_registry.by_role("stage")
        assert len(result) == 1
        assert result[0] is s

    def test_by_role_multiple(self, empty_registry):
        """同 role 多个 Stage."""
        s1 = _make_stub("a", role="metric")
        s2 = _make_stub("b", role="metric")
        empty_registry.register(s1)
        empty_registry.register(s2)
        result = empty_registry.by_role("metric")
        assert len(result) == 2
        assert s1 in result
        assert s2 in result

    def test_by_role_empty(self, empty_registry):
        """无对应 role 返回空 list."""
        assert empty_registry.by_role("nonexistent") == []

    def test_by_role_after_unregister(self, empty_registry):
        """注销后 by_role 不再返回."""
        s1 = _make_stub("a", role="metric")
        s2 = _make_stub("b", role="metric")
        empty_registry.register(s1)
        empty_registry.register(s2)
        empty_registry.unregister("a")
        result = empty_registry.by_role("metric")
        assert len(result) == 1
        assert result[0] is s2


class TestStageRegistryByCapability:
    """by_capability() O(1) 索引查询."""

    def test_by_capability_single(self, empty_registry):
        s = _make_stub("alpha", role="stage", capabilities=frozenset({"selects_provider"}))
        empty_registry.register(s)
        result = empty_registry.by_capability("selects_provider")
        assert len(result) == 1
        assert result[0] is s

    def test_by_capability_multiple(self, empty_registry):
        """同 capability 多个 Stage."""
        s1 = _make_stub("a", role="stage", capabilities=frozenset({"controls_flow"}))
        s2 = _make_stub("b", role="condition", capabilities=frozenset({"controls_flow"}))
        empty_registry.register(s1)
        empty_registry.register(s2)
        result = empty_registry.by_capability("controls_flow")
        assert len(result) == 2

    def test_by_capability_empty(self, empty_registry):
        assert empty_registry.by_capability("nonexistent") == []

    def test_by_capability_multiple_caps_per_stage(self, empty_registry):
        """一个 Stage 有多个 capabilities, 每个都索引到."""
        s = _make_stub(
            "multi",
            role="stage",
            capabilities=frozenset({"cap_a", "cap_b", "cap_c"}),
        )
        empty_registry.register(s)
        assert len(empty_registry.by_capability("cap_a")) == 1
        assert len(empty_registry.by_capability("cap_b")) == 1
        assert len(empty_registry.by_capability("cap_c")) == 1


class TestStageRegistryAllRolesCapabilities:
    """all() / roles() / capabilities()."""

    def test_all_returns_all(self, empty_registry):
        s1 = _make_stub("a", role="stage")
        s2 = _make_stub("b", role="metric")
        empty_registry.register(s1)
        empty_registry.register(s2)
        result = empty_registry.all()
        assert len(result) == 2
        assert s1 in result
        assert s2 in result

    def test_roles_returns_all_roles(self, empty_registry):
        empty_registry.register(_make_stub("a", role="stage"))
        empty_registry.register(_make_stub("b", role="metric"))
        empty_registry.register(_make_stub("c", role="checkpoint"))
        assert empty_registry.roles() == {"stage", "metric", "checkpoint"}

    def test_capabilities_returns_all_capabilities(self, empty_registry):
        empty_registry.register(
            _make_stub("a", role="stage", capabilities=frozenset({"cap1", "cap2"}))
        )
        empty_registry.register(
            _make_stub("b", role="metric", capabilities=frozenset({"cap3"}))
        )
        assert empty_registry.capabilities() == {"cap1", "cap2", "cap3"}


class TestStageRegistryContainerSemantics:
    """Python 容器语义: __contains__ / __len__ / __iter__ / __getitem__."""

    def test_contains(self, empty_registry):
        empty_registry.register(_make_stub("alpha", role="stage"))
        assert "alpha" in empty_registry
        assert "nonexistent" not in empty_registry

    def test_len(self, empty_registry):
        empty_registry.register(_make_stub("a", role="stage"))
        empty_registry.register(_make_stub("b", role="metric"))
        assert len(empty_registry) == 2

    def test_iter(self, empty_registry):
        empty_registry.register(_make_stub("a", role="stage"))
        empty_registry.register(_make_stub("b", role="metric"))
        names = list(iter(empty_registry))
        assert set(names) == {"a", "b"}

    def test_getitem(self, empty_registry):
        stage = _make_stub("alpha", role="stage")
        empty_registry.register(stage)
        assert empty_registry["alpha"] is stage

    def test_getitem_raises_on_missing(self, empty_registry):
        with pytest.raises(KeyError, match="not found"):
            _ = empty_registry["nonexistent"]


class TestStageRegistryIndexConsistency:
    """注册/注销后索引一致性."""

    def test_register_unregister_index_consistency(self, empty_registry):
        """register → unregister → register 保持索引一致."""
        s = _make_stub("x", role="stage", capabilities=frozenset({"cap1"}))
        empty_registry.register(s)
        assert len(empty_registry.by_role("stage")) == 1
        assert len(empty_registry.by_capability("cap1")) == 1
        empty_registry.unregister("x")
        assert len(empty_registry.by_role("stage")) == 0
        assert len(empty_registry.by_capability("cap1")) == 0
        # re-register
        s2 = _make_stub("x", role="stage", capabilities=frozenset({"cap1"}))
        empty_registry.register(s2)
        assert len(empty_registry.by_role("stage")) == 1
        assert len(empty_registry.by_capability("cap1")) == 1

    def test_replace_preserves_indices(self, empty_registry):
        """replace=True 替换后索引仍指向新 Stage."""
        s1 = _make_stub("x", role="stage", capabilities=frozenset({"cap1"}))
        s2 = _make_stub("x", role="stage", capabilities=frozenset({"cap1"}))
        empty_registry.register(s1)
        empty_registry.register(s2, replace=True)
        assert len(empty_registry) == 1
        assert empty_registry.lookup("x") is s2
        assert empty_registry.by_role("stage")[0] is s2
        assert empty_registry.by_capability("cap1")[0] is s2


# ─────────────────────────────────────────────────────────────
# TestDescribe (T2 采纳 ChatGPT 9.93/10)
# ─────────────────────────────────────────────────────────────

class TestDescribe:
    """describe(name) 返回 StageDescriptor (T2 采纳)."""

    def test_describe_returns_descriptor(self, empty_registry):
        stage = _make_stub("alpha", role="stage", capabilities=frozenset({"cap1"}))
        empty_registry.register(stage)
        desc = empty_registry.describe("alpha")
        assert desc is not None
        assert desc.name == "alpha"
        assert desc.role == "stage"
        assert desc.capabilities == frozenset({"cap1"})

    def test_describe_nonexisting_returns_none(self, empty_registry):
        assert empty_registry.describe("nonexistent") is None

    def test_describe_does_not_return_stage_instance(self, empty_registry):
        """describe 返回 StageDescriptor, 不返回 Stage 实例."""
        stage = _make_stub("alpha", role="stage")
        empty_registry.register(stage)
        desc = empty_registry.describe("alpha")
        assert isinstance(desc, StageDescriptor)
        assert desc is not stage  # 不是 Stage 实例


# ─────────────────────────────────────────────────────────────
# TestDefaultOrder (Q3 重构 采纳 ChatGPT 9.93/10)
# ─────────────────────────────────────────────────────────────

class TestDefaultOrder:
    """default_order() 暴露 Pipeline 构造顺序 (Q3 重构)."""

    def test_default_order_returns_tuple(self, empty_registry):
        """default_order() 返回 tuple (非 list, 不可变)."""
        order = empty_registry.default_order()
        assert isinstance(order, tuple)
        assert order == ("stage", "metric", "checkpoint", "condition")

    def test_default_order_is_class_attribute(self):
        """DEFAULT_ORDER 是 class attribute."""
        assert StageRegistry.DEFAULT_ORDER == ("stage", "metric", "checkpoint", "condition")


# ─────────────────────────────────────────────────────────────
# §6.2 TestDefaultRegistry — Singleton + Built-in (8 tests)
# ─────────────────────────────────────────────────────────────

class TestDefaultRegistry:
    """default_registry() singleton + built-in Stage auto-register."""

    def test_default_registry_singleton(self, clean_default):
        """多次调用返回同一 instance."""
        r1 = default_registry()
        r2 = default_registry()
        assert r1 is r2

    def test_default_registry_has_builtin_stages(self, clean_default):
        """5 个 built-in Stage 已注册."""
        r = default_registry()
        assert len(r) == 5
        assert "route" in r
        assert "metrics" in r
        assert "retry" in r
        assert "checkpoint" in r
        assert "condition" in r

    def test_default_registry_builtin_roles(self, clean_default):
        """built-in Stage 覆盖 5 个 role."""
        r = default_registry()
        assert r.roles() == {"stage", "metric", "retry", "checkpoint", "condition"}

    def test_default_registry_builtin_capabilities(self, clean_default):
        """built-in Stage 覆盖 5 个 capability."""
        r = default_registry()
        assert "selects_provider" in r.capabilities()
        assert "collects_metrics" in r.capabilities()
        assert "retries" in r.capabilities()
        assert "persists_state" in r.capabilities()
        assert "controls_flow" in r.capabilities()

    def test_default_registry_persists_across_calls(self, clean_default):
        """跨调用持久 (singleton)."""
        r1 = default_registry()
        stage = _make_stub("custom", role="stage")
        r1.register(stage)
        r2 = default_registry()
        assert r2.lookup("custom") is stage

    def test_default_registry_register_third_party(self, clean_default):
        """第三方 Stage 可注册到 default registry."""
        r = default_registry()
        stage = _make_stub("my_plugin", role="stage", capabilities=frozenset({"custom_cap"}))
        r.register(stage)
        assert r.lookup("my_plugin") is stage
        assert r.by_capability("custom_cap")[0] is stage

    def test_reset_default_registry_reregisters_builtins(self, clean_default):
        """T1: reset_default_registry() → 下次 default_registry() 重新注册 built-in."""
        r1 = default_registry()
        assert len(r1) == 5
        # Add third-party
        r1.register(_make_stub("custom", role="stage"))
        assert len(r1) == 6
        # Reset
        reset_default_registry()
        r2 = default_registry()
        assert len(r2) == 5  # built-in only, third-party gone
        assert "custom" not in r2

    def test_default_registry_replace_builtin(self, clean_default):
        """replace=True 替换 built-in Stage."""
        r = default_registry()
        original = r.lookup("metrics")
        replacement = _make_stub("metrics", role="metric")
        r.register(replacement, replace=True)
        assert r.lookup("metrics") is replacement
        assert r.lookup("metrics") is not original


# ─────────────────────────────────────────────────────────────
# §6.4 TestThirdPartyStageIntegration — 第三方 Stage 集成 (4 tests)
# ─────────────────────────────────────────────────────────────

class TestThirdPartyStageIntegration:
    """第三方 Stage 集成测试."""

    def test_third_party_register_visible(self, empty_registry):
        """注册后立即可查."""
        stage = _make_stub(
            "my_plugin",
            role="stage",
            capabilities=frozenset({"custom_cap"}),
        )
        empty_registry.register(stage)
        assert empty_registry.lookup("my_plugin") is stage
        assert "my_plugin" in empty_registry

    def test_third_party_by_capability(self, empty_registry):
        """按 capability 找到第三方 Stage."""
        stage = _make_stub(
            "my_plugin",
            role="stage",
            capabilities=frozenset({"custom_cap"}),
        )
        empty_registry.register(stage)
        result = empty_registry.by_capability("custom_cap")
        assert len(result) == 1
        assert result[0] is stage

    def test_third_party_replace_false_raises(self, empty_registry):
        """重复 name 且 replace=False → KeyError."""
        s1 = _make_stub("shared_name", role="stage")
        s2 = _make_stub("shared_name", role="metric")
        empty_registry.register(s1)
        with pytest.raises(KeyError):
            empty_registry.register(s2)

    def test_third_party_appears_in_all(self, empty_registry):
        """第三方 Stage 出现在 all() 中."""
        empty_registry.register(_make_stub("builtin_a", role="stage"))
        empty_registry.register(_make_stub("plugin_b", role="metric"))
        all_stages = empty_registry.all()
        assert len(all_stages) == 2


# ─────────────────────────────────────────────────────────────
# Rev1 R4: Misuse Guard — RouteStage / CheckpointStage (3 tests)
# ─────────────────────────────────────────────────────────────

class TestMisuseGuard:
    """Rev1 R4 (ChatGPT 9.72/10): RouteStage / CheckpointStage misuse guard.

    验证: 从 default_registry 取出的 stub-deps Stage 不应被直接执行。
    若被误用, 应抛 RuntimeError (Architecture misuse error),
    而不是 AttributeError / NoneType error / 静默吞掉。
    """

    def test_route_stage_stub_router_raises(self, clean_default):
        """RouteStage(router=None) 被误调用 → RuntimeError, 非 AttributeError."""
        from planner.stage_registry import default_registry
        from planner.pipeline import ExecutionContext
        from core.task import Task

        stage = default_registry().lookup("route")
        assert stage is not None
        # router is None (stub)
        assert stage.router is None

        task = Task(
            content="hello",
            task_id="t1",
            capabilities=["text"],
        )
        ctx = ExecutionContext(task=task)

        with pytest.raises(RuntimeError, match="discovery-only"):
            stage(ctx)

    def test_checkpoint_stage_stub_store_raises(self, clean_default):
        """CheckpointStage(store=_NullStore()) 被误调用 → RuntimeError.

        验证 _NullStore.is_registry_stub = True 标记生效。
        """
        from planner.stage_registry import default_registry
        from planner.pipeline import ExecutionContext
        from core.task import Task
        from core.bridge import BridgeResult

        stage = default_registry().lookup("checkpoint")
        assert stage is not None
        # store is _NullStore (stub)
        assert getattr(stage.store, "is_registry_stub", False) is True

        task = Task(
            content="hello",
            task_id="t2",
            capabilities=["text"],
        )
        br = BridgeResult(success=True, output="ok", artifacts=[])
        ctx = ExecutionContext(task=task, bridge_result=br)

        with pytest.raises(RuntimeError, match="discovery-only"):
            stage(ctx)

    def test_null_store_marker_present(self):
        """_NullStore 暴露 is_registry_stub=True 类属性."""
        from planner.stage_registry import _NullStore

        # 类属性
        assert _NullStore.is_registry_stub is True
        # 实例属性 (getattr)
        instance = _NullStore()
        assert getattr(instance, "is_registry_stub", False) is True
