# AI Hub — Stage Registry Introspection Tests (V1.0.9, ADR-0030 Accepted 9.62/10)
#
# 测试 V1.0.9 Introspection 能力:
#   - StageInfo / StageSummary frozen dataclass
#   - register() V1.0.9 扩展 (source / requires, V1.0.8 向后兼容)
#   - info() / describe_all() / summary()
#   - list_builtin() / list_third_party()
#   - find_stages_needing(*deps) (AND 语义)
#   - to_dict() / to_json() (含 R4 serialization stability test)
#   - unregister / clear 同步清理 _info
#   - default_registry() V1.0.9 (built-in source + requires 声明)
#
# 覆盖 ADR-0030 §6.1-§6.10 + R4 stability test

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from planner.stage_descriptor import StageDescriptor
from planner.stage_registry import (
    VALID_SOURCES,
    StageInfo,
    StageRegistry,
    StageSummary,
    default_registry,
    reset_default_registry,
)


# ─────────────────────────────────────────────────────────────
# Helpers — Stub Stage factory
# ─────────────────────────────────────────────────────────────

def _make_stub(
    name: str,
    role: str = "stage",
    capabilities=frozenset(),  # type: ignore
):
    """Create a stub Stage instance with given descriptor fields."""

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
    return StageRegistry()


@pytest.fixture
def clean_default():
    reset_default_registry()
    yield
    reset_default_registry()


# ─────────────────────────────────────────────────────────────
# §6.1 StageInfo / StageSummary 数据结构 (3 tests)
# ─────────────────────────────────────────────────────────────

class TestStageInfoDataclass:
    """StageInfo / StageSummary frozen dataclass 测试."""

    def test_stage_info_frozen(self):
        """StageInfo 是 frozen, 修改 raise FrozenInstanceError."""
        d = StageDescriptor(name="route", role="stage")
        info = StageInfo(descriptor=d, source="builtin", requires=("router",))
        with pytest.raises(FrozenInstanceError):
            info.source = "third_party"  # type: ignore
        with pytest.raises(FrozenInstanceError):
            info.requires = ()  # type: ignore

    def test_stage_summary_frozen(self):
        """StageSummary 是 frozen."""
        s = StageSummary(
            name="route",
            role="stage",
            capabilities=frozenset({"selects_provider"}),
            source="builtin",
            requires=("router",),
        )
        with pytest.raises(FrozenInstanceError):
            s.name = "other"  # type: ignore

    def test_stage_info_defaults(self):
        """StageInfo 默认 source="third_party" / requires=() / registered_at=now."""
        d = StageDescriptor(name="my_stage")
        info = StageInfo(descriptor=d)
        assert info.source == "third_party"
        assert info.requires == ()
        # registered_at 是 datetime (R3 修正, 非 Optional)
        assert isinstance(info.registered_at, datetime)


# ─────────────────────────────────────────────────────────────
# §6.2 register() V1.0.9 扩展 (5 tests)
# ─────────────────────────────────────────────────────────────

class TestRegisterV19Extension:
    """register() V1.0.9 扩展 source / requires 参数."""

    def test_register_with_source_builtin(self, empty_registry):
        """source="builtin" 被记录."""
        stage = _make_stub("my_stage")
        empty_registry.register(stage, source="builtin")
        info = empty_registry.info("my_stage")
        assert info is not None
        assert info.source == "builtin"

    def test_register_with_source_third_party(self, empty_registry):
        """source="third_party" 被记录 (默认)."""
        stage = _make_stub("my_stage")
        empty_registry.register(stage, source="third_party")
        info = empty_registry.info("my_stage")
        assert info is not None
        assert info.source == "third_party"

    def test_register_with_requires(self, empty_registry):
        """requires=("router",) 被记录."""
        stage = _make_stub("my_stage")
        empty_registry.register(stage, requires=("router",))
        info = empty_registry.info("my_stage")
        assert info is not None
        assert info.requires == ("router",)

    def test_register_v108_compat_no_source(self, empty_registry):
        """V1.0.8 旧调用 register(stage) 默认 source="third_party"."""
        stage = _make_stub("my_stage")
        empty_registry.register(stage)  # V1.0.8 风格
        info = empty_registry.info("my_stage")
        assert info is not None
        assert info.source == "third_party"
        assert info.requires == ()

    def test_register_v108_compat_replace_only(self, empty_registry):
        """V1.0.8 旧调用 register(stage, replace=True) 仍工作."""
        s1 = _make_stub("shared_name", role="stage")
        s2 = _make_stub("shared_name", role="metric")
        empty_registry.register(s1)
        # V1.0.8 风格: 只传 replace=True, 不传 source / requires
        empty_registry.register(s2, replace=True)
        info = empty_registry.info("shared_name")
        assert info is not None
        # 替换后 source 重置为默认 "third_party"
        assert info.source == "third_party"


# ─────────────────────────────────────────────────────────────
# §6.3 info() / describe_all() (4 tests)
# ─────────────────────────────────────────────────────────────

class TestInfoDescribeAll:
    """info() / describe_all() 测试."""

    def test_info_returns_stage_info(self, empty_registry):
        """info(name) 返回 StageInfo."""
        stage = _make_stub("route", role="stage", capabilities=frozenset({"selects_provider"}))
        empty_registry.register(stage, source="builtin", requires=("router",))
        info = empty_registry.info("route")
        assert info is not None
        assert info.descriptor.name == "route"
        assert info.descriptor.role == "stage"
        assert info.source == "builtin"
        assert info.requires == ("router",)
        assert isinstance(info.registered_at, datetime)

    def test_info_not_found(self, empty_registry):
        """info("unknown") 返回 None."""
        assert empty_registry.info("unknown") is None

    def test_describe_all_returns_dict(self, empty_registry):
        """describe_all() 返回 dict (name → StageDescriptor)."""
        empty_registry.register(_make_stub("a", role="stage"))
        empty_registry.register(_make_stub("b", role="metric"))
        all_desc = empty_registry.describe_all()
        assert isinstance(all_desc, dict)
        assert set(all_desc.keys()) == {"a", "b"}
        assert all_desc["a"].name == "a"
        assert all_desc["b"].role == "metric"

    def test_describe_all_empty_registry(self, empty_registry):
        """空 Registry 返回 {}."""
        assert empty_registry.describe_all() == {}


# ─────────────────────────────────────────────────────────────
# §6.4 summary() (3 tests)
# ─────────────────────────────────────────────────────────────

class TestSummary:
    """summary() 测试."""

    def test_summary_returns_list(self, empty_registry):
        """summary() 返回 List[StageSummary]."""
        empty_registry.register(
            _make_stub("route", role="stage", capabilities=frozenset({"selects_provider"})),
            source="builtin",
            requires=("router",),
        )
        empty_registry.register(
            _make_stub("metrics", role="metric"),
            source="builtin",
        )
        result = empty_registry.summary()
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(s, StageSummary) for s in result)
        # 第一个 Stage
        assert result[0].name == "route"
        assert result[0].role == "stage"
        assert result[0].source == "builtin"
        assert result[0].requires == ("router",)
        assert "selects_provider" in result[0].capabilities

    def test_summary_empty_registry(self, empty_registry):
        """空 Registry 返回 []."""
        assert empty_registry.summary() == []

    def test_summary_includes_source_requires(self, empty_registry):
        """summary 包含 source / requires 字段."""
        empty_registry.register(
            _make_stub("a"),
            source="test",
            requires=("router", "store"),
        )
        s = empty_registry.summary()[0]
        assert s.source == "test"
        assert s.requires == ("router", "store")


# ─────────────────────────────────────────────────────────────
# §6.5 list_builtin() / list_third_party() (4 tests)
# ─────────────────────────────────────────────────────────────

class TestListBySource:
    """list_builtin() / list_third_party() 测试."""

    def test_list_builtin_default_registry(self, clean_default):
        """default_registry 有 5 个 built-in (route / retry / checkpoint / condition / metrics)."""
        reg = default_registry()
        builtins = reg.list_builtin()
        assert set(builtins) == {"route", "retry", "checkpoint", "condition", "metrics"}
        assert len(builtins) == 5

    def test_list_builtin_empty_registry(self, empty_registry):
        """空 Registry 返回 []."""
        assert empty_registry.list_builtin() == []

    def test_list_third_party_after_register(self, empty_registry):
        """注册第三方后 list_third_party 返回它."""
        empty_registry.register(_make_stub("plugin_a"), source="third_party")
        empty_registry.register(_make_stub("plugin_b"), source="third_party")
        third_party = empty_registry.list_third_party()
        assert set(third_party) == {"plugin_a", "plugin_b"}

    def test_list_builtin_excludes_third_party(self, empty_registry):
        """built-in / third-party 互斥."""
        empty_registry.register(_make_stub("builtin_a"), source="builtin")
        empty_registry.register(_make_stub("plugin_b"), source="third_party")
        builtins = empty_registry.list_builtin()
        third_party = empty_registry.list_third_party()
        assert "builtin_a" in builtins
        assert "plugin_b" not in builtins
        assert "plugin_b" in third_party
        assert "builtin_a" not in third_party


# ─────────────────────────────────────────────────────────────
# §6.6 find_stages_needing() (5 tests, R5 AND 语义)
# ─────────────────────────────────────────────────────────────

class TestFindStagesNeeding:
    """find_stages_needing(*deps) 测试 (R5 AND 语义)."""

    def test_find_stages_needing_router(self, clean_default):
        """find_stages_needing("router") 返回 ["route"]."""
        reg = default_registry()
        result = reg.find_stages_needing("router")
        assert result == ["route"]

    def test_find_stages_needing_store(self, clean_default):
        """find_stages_needing("store") 返回 ["checkpoint"]."""
        reg = default_registry()
        result = reg.find_stages_needing("store")
        assert result == ["checkpoint"]

    def test_find_stages_needing_multiple_and(self, clean_default):
        """find_stages_needing("router", "store") 返回 [] (AND 语义, 无 Stage 同时需要两者)."""
        reg = default_registry()
        # route requires ("router",), checkpoint requires ("store",)
        # AND query: 同时需要 router 和 store 的 Stage → []
        result = reg.find_stages_needing("router", "store")
        assert result == []

    def test_find_stages_needing_empty_args(self, clean_default):
        """find_stages_needing() (无参数) 返回 []."""
        reg = default_registry()
        assert reg.find_stages_needing() == []

    def test_find_stages_needing_unknown_dep(self, clean_default):
        """find_stages_needing("nonexistent") 返回 []."""
        reg = default_registry()
        assert reg.find_stages_needing("nonexistent") == []

    def test_find_stages_needing_custom_stage(self, empty_registry):
        """自定义 Stage requires=("router", "store") 应被 AND query 找到."""
        empty_registry.register(
            _make_stub("custom"),
            requires=("router", "store"),
        )
        # AND query: 同时需要 router 和 store
        result = empty_registry.find_stages_needing("router", "store")
        assert result == ["custom"]
        # 单独查 router 也应找到 (因为 requires ⊇ {router})
        assert "custom" in empty_registry.find_stages_needing("router")
        # 单独查 store 也应找到
        assert "custom" in empty_registry.find_stages_needing("store")


# ─────────────────────────────────────────────────────────────
# §6.7 to_dict() / to_json() (6 tests, R4 含 stability test)
# ─────────────────────────────────────────────────────────────

class TestSerialization:
    """to_dict() / to_json() 测试 (含 R4 stability test)."""

    def test_to_dict_has_stages_key(self, clean_default):
        """to_dict() 有 "stages" key."""
        d = default_registry().to_dict()
        assert "stages" in d
        assert isinstance(d["stages"], list)
        # 5 个 built-in Stage
        assert len(d["stages"]) == 5

    def test_to_dict_has_roles_capabilities_default_order(self, clean_default):
        """to_dict() 有 roles / capabilities / default_order."""
        d = default_registry().to_dict()
        assert set(d.keys()) == {"stages", "roles", "capabilities", "default_order"}
        assert isinstance(d["roles"], list)
        assert isinstance(d["capabilities"], list)
        assert isinstance(d["default_order"], list)
        assert d["default_order"] == ["stage", "metric", "checkpoint", "condition"]

    def test_to_dict_descriptor_expanded(self, clean_default):
        """每个 stage 的 descriptor 是展开的 dict."""
        d = default_registry().to_dict()
        for stage in d["stages"]:
            assert isinstance(stage["descriptor"], dict)
            assert "name" in stage["descriptor"]
            assert "role" in stage["descriptor"]
            assert "capabilities" in stage["descriptor"]

    def test_to_json_valid_json(self, clean_default):
        """to_json() 是合法 JSON."""
        s = default_registry().to_json()
        data = json.loads(s)
        assert isinstance(data, dict)
        assert "stages" in data

    def test_to_json_indent(self, clean_default):
        """indent 参数生效."""
        s_indented = default_registry().to_json(indent=2)
        s_compact = default_registry().to_json(indent=None)
        # indented 应该有换行, compact 应该没有 (或更少)
        assert "\n" in s_indented
        assert "\n" not in s_compact

    def test_to_json_schema_stable(self, clean_default):
        """R4 (ChatGPT 9.62/10): to_json() schema keys 跨版本稳定.

        避免 ADR-0031 重构时改坏 schema.
        """
        data = json.loads(default_registry().to_json())
        # Top-level keys
        assert set(data.keys()) == {"stages", "roles", "capabilities", "default_order"}
        # 每个 stage 的 keys
        for stage in data["stages"]:
            assert set(stage.keys()) == {
                "name", "descriptor", "source", "requires", "registered_at"
            }
            # descriptor keys
            assert set(stage["descriptor"].keys()) == {
                "name", "role", "version", "capabilities", "idempotent",
                "has_side_effects", "always_run_after_stop", "experimental",
                "description", "owner",
            }
            # source 是 string
            assert isinstance(stage["source"], str)
            # requires 是 list
            assert isinstance(stage["requires"], list)
            # registered_at 是 ISO 字符串
            assert isinstance(stage["registered_at"], str)
            # 验证可解析回 datetime
            datetime.fromisoformat(stage["registered_at"])


# ─────────────────────────────────────────────────────────────
# §6.8 unregister / clear 同步清理 (3 tests)
# ─────────────────────────────────────────────────────────────

class TestInfoCleanup:
    """unregister / clear 同步清理 _info."""

    def test_unregister_removes_info(self, empty_registry):
        """unregister 后 info(name) 返回 None."""
        empty_registry.register(_make_stub("a"), source="builtin")
        assert empty_registry.info("a") is not None
        empty_registry.unregister("a")
        assert empty_registry.info("a") is None

    def test_clear_removes_all_info(self, empty_registry):
        """clear 后 _info 为空."""
        empty_registry.register(_make_stub("a"))
        empty_registry.register(_make_stub("b"))
        assert len(empty_registry.info("a").requires) == 0  # type: ignore
        empty_registry.clear()
        assert empty_registry.info("a") is None
        assert empty_registry.info("b") is None
        assert empty_registry.summary() == []

    def test_replace_updates_info(self, empty_registry):
        """register(replace=True) 更新 StageInfo."""
        s1 = _make_stub("shared", role="stage")
        s2 = _make_stub("shared", role="metric")
        empty_registry.register(s1, source="builtin", requires=("router",))
        info1 = empty_registry.info("shared")
        assert info1.source == "builtin"
        assert info1.requires == ("router",)

        # replace with different source / requires
        empty_registry.register(s2, replace=True, source="third_party", requires=("store",))
        info2 = empty_registry.info("shared")
        assert info2.source == "third_party"
        assert info2.requires == ("store",)
        # descriptor 也应更新
        assert info2.descriptor.role == "metric"


# ─────────────────────────────────────────────────────────────
# §6.9 default_registry() V1.0.9 (3 tests)
# ─────────────────────────────────────────────────────────────

class TestDefaultRegistryV19:
    """default_registry() V1.0.9 built-in source + requires 声明."""

    def test_default_registry_builtin_has_source(self, clean_default):
        """5 个 built-in 全部 source="builtin"."""
        reg = default_registry()
        for name in reg.list_builtin():
            info = reg.info(name)
            assert info is not None
            assert info.source == "builtin"

    def test_default_registry_route_requires_router(self, clean_default):
        """route 的 requires=("router",)."""
        reg = default_registry()
        info = reg.info("route")
        assert info is not None
        assert info.requires == ("router",)

    def test_default_registry_checkpoint_requires_store(self, clean_default):
        """checkpoint 的 requires=("store",)."""
        reg = default_registry()
        info = reg.info("checkpoint")
        assert info is not None
        assert info.requires == ("store",)

    def test_default_registry_zero_dep_stages(self, clean_default):
        """retry / condition / metrics 的 requires=()."""
        reg = default_registry()
        for name in ("retry", "condition", "metrics"):
            info = reg.info(name)
            assert info is not None
            assert info.requires == ()


# ─────────────────────────────────────────────────────────────
# §6.10 VALID_SOURCES warning (R2, 2 tests)
# ─────────────────────────────────────────────────────────────

class TestValidSourcesWarning:
    """R2 (ChatGPT 9.62/10): source 不在 VALID_SOURCES 时 warning (不 raise)."""

    def test_valid_sources_contains_expected(self):
        """VALID_SOURCES 包含 builtin / third_party / test."""
        assert "builtin" in VALID_SOURCES
        assert "third_party" in VALID_SOURCES
        assert "test" in VALID_SOURCES
        assert len(VALID_SOURCES) == 3

    def test_register_unknown_source_warns_not_raises(self, empty_registry, caplog):
        """register(source="unknown") 应 warning, 不 raise."""
        import logging
        with caplog.at_level(logging.WARNING, logger="planner.stage_registry"):
            empty_registry.register(
                _make_stub("unknown_src"),
                source="internal_plugin",  # 不在 VALID_SOURCES
            )
        # 应该注册成功
        assert "unknown_src" in empty_registry
        # 应该有 warning
        assert any(
            "unknown source" in rec.message.lower()
            for rec in caplog.records
        ), f"Expected warning about unknown source, got: {[r.message for r in caplog.records]}"
