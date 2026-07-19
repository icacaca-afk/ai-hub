# AI Hub — Default Pipeline Factory Tests (V1.0.8, ADR-0029 Accepted 9.93/10)
#
# 测试 planner.stage_registry.default_pipeline() 工厂:
#   - 返回 ExecutionPipeline 实例
#   - 包含 built-in Stage (route / metrics / condition)
#   - role 顺序: pre_bridge=[route], post_bridge=[metrics, (checkpoint), condition]
#   - 接受 custom registry 参数
#   - store=None → skip checkpoint
#   - store=MemoryStore → 包含 checkpoint
#
# 覆盖 ADR §6.3 (Default Pipeline 工厂测试, 5+).

from __future__ import annotations

import pytest

from planner.stage_descriptor import StageDescriptor, get_descriptor
from planner.stage_registry import (
    StageRegistry,
    default_pipeline,
    default_registry,
    reset_default_registry,
)


# ─────────────────────────────────────────────────────────────
# Helpers — Fake Router / Fake Store (避免依赖真实 Router/SQLite)
# ─────────────────────────────────────────────────────────────

class _FakeRouter:
    """Minimal router stub (route() returns None = no provider)."""

    def route(self, task):
        return None


class _FakeStore:
    """Minimal ExecutionStore stub (append is no-op)."""

    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


def _make_stub(name, role="stage", capabilities=frozenset()):  # type: ignore
    """Create a stub Stage instance for testing."""

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
def clean_default():
    """Reset default_registry before + after test."""
    reset_default_registry()
    yield
    reset_default_registry()


@pytest.fixture
def fake_router():
    return _FakeRouter()


@pytest.fixture
def fake_store():
    return _FakeStore()


# ─────────────────────────────────────────────────────────────
# §6.3 TestDefaultPipelineFactory — Default Pipeline 工厂 (7 tests)
# ─────────────────────────────────────────────────────────────

class TestDefaultPipelineFactory:
    """default_pipeline(router, store, registry) 工厂."""

    def test_default_pipeline_returns_pipeline(self, clean_default, fake_router):
        """返回 ExecutionPipeline 实例."""
        from planner.pipeline import ExecutionPipeline
        pipeline = default_pipeline(router=fake_router)
        assert isinstance(pipeline, ExecutionPipeline)

    def test_default_pipeline_includes_route_stage(self, clean_default, fake_router):
        """pre_bridge 包含 RouteStage (role='stage')."""
        pipeline = default_pipeline(router=fake_router)
        assert len(pipeline.pre_bridge_stages) >= 1
        route_stage = pipeline.pre_bridge_stages[0]
        desc = get_descriptor(route_stage)
        assert desc.name == "route"
        assert desc.role == "stage"

    def test_default_pipeline_includes_metrics_and_condition(self, clean_default, fake_router):
        """post_bridge 包含 MetricsStage + ConditionStage."""
        pipeline = default_pipeline(router=fake_router)
        post_names = [get_descriptor(s).name for s in pipeline.post_bridge_stages]
        assert "metrics" in post_names
        assert "condition" in post_names

    def test_default_pipeline_role_order(self, clean_default, fake_router):
        """顺序: pre=[route], post=[metrics, condition] (无 store, 无 checkpoint)."""
        pipeline = default_pipeline(router=fake_router)
        # pre_bridge: route
        assert len(pipeline.pre_bridge_stages) == 1
        assert get_descriptor(pipeline.pre_bridge_stages[0]).name == "route"
        # post_bridge: metrics, condition (no checkpoint without store)
        post_names = [get_descriptor(s).name for s in pipeline.post_bridge_stages]
        assert post_names == ["metrics", "condition"]

    def test_default_pipeline_with_store_includes_checkpoint(
        self, clean_default, fake_router, fake_store
    ):
        """store → post_bridge 包含 CheckpointStage."""
        pipeline = default_pipeline(router=fake_router, store=fake_store)
        post_names = [get_descriptor(s).name for s in pipeline.post_bridge_stages]
        assert "checkpoint" in post_names
        # Order: metrics, checkpoint, condition
        assert post_names == ["metrics", "checkpoint", "condition"]

    def test_default_pipeline_without_store_skips_checkpoint(self, clean_default, fake_router):
        """store=None → 不包含 CheckpointStage."""
        pipeline = default_pipeline(router=fake_router, store=None)
        post_names = [get_descriptor(s).name for s in pipeline.post_bridge_stages]
        assert "checkpoint" not in post_names

    def test_default_pipeline_with_custom_registry(self, fake_router):
        """接 registry 参数 (自定义 Stage 集合)."""
        custom_reg = StageRegistry()
        custom_reg.register(_make_stub("custom_route", role="stage"))
        custom_reg.register(_make_stub("custom_metrics", role="metric"))
        custom_reg.register(_make_stub("custom_condition", role="condition"))
        pipeline = default_pipeline(router=fake_router, registry=custom_reg)
        # pre_bridge: RouteStage (real router, from role="stage")
        assert len(pipeline.pre_bridge_stages) == 1
        # post_bridge: custom_metrics, custom_condition (from registry)
        post_names = [get_descriptor(s).name for s in pipeline.post_bridge_stages]
        assert "custom_metrics" in post_names
        assert "custom_condition" in post_names


# ─────────────────────────────────────────────────────────────
# TestDefaultPipelineRouterInjection — RouteStage 用 real router (3 tests)
# ─────────────────────────────────────────────────────────────

class TestDefaultPipelineRouterInjection:
    """default_pipeline(router) 注入 real router 到 RouteStage."""

    def test_route_stage_uses_real_router(self, clean_default, fake_router):
        """RouteStage.router 是传入的 router (非 None)."""
        pipeline = default_pipeline(router=fake_router)
        route_stage = pipeline.pre_bridge_stages[0]
        assert route_stage.router is fake_router

    def test_route_stage_router_not_none(self, clean_default, fake_router):
        """RouteStage.router 不是 None (registry stub 是 None)."""
        pipeline = default_pipeline(router=fake_router)
        route_stage = pipeline.pre_bridge_stages[0]
        assert route_stage.router is not None

    def test_checkpoint_stage_uses_real_store(self, clean_default, fake_router, fake_store):
        """CheckpointStage.store 是传入的 store (非 _NullStore)."""
        pipeline = default_pipeline(router=fake_router, store=fake_store)
        for stage in pipeline.post_bridge_stages:
            desc = get_descriptor(stage)
            if desc.name == "checkpoint":
                assert stage.store is fake_store
                return
        pytest.fail("CheckpointStage not found in post_bridge_stages")
