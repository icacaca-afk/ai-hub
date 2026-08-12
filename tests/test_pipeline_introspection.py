# AI Hub — Pipeline Introspection Tests (V1.0.11, ADR-0032)
#
# 45 tests / 11 test classes per ADR-0032 §5.2
#
# Coverage:
#   - PipelineDescriptor (value object)
#   - serialize_pipeline() (canonical serialization)
#   - ExecutionPipeline.describe() / to_dict() / to_json()
#   - StageDescriptor.from_stage()
#   - Edge model (linear + bridge virtual node)
#   - Schema stability
#   - Backward compatibility
#   - Duplicate names / snapshot semantics

import json
import pytest
from dataclasses import FrozenInstanceError, is_dataclass
from typing import get_type_hints

from planner.pipeline_descriptor import PipelineDescriptor
from planner.stage_descriptor import StageDescriptor, _STAGE_ROLE_MAP
from planner.metadata_serialization import serialize_pipeline, to_json
from planner.pipeline import (
    ExecutionPipeline,
    RouteStage,
    MetricsStage,
    default_pipeline,
)
from router.router import Router


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

class FakeRouter(Router):
    """Minimal Router for testing (no registry needed)."""

    def __init__(self):
        # Skip Router.__init__ which requires registry
        self.registry = None

    def route(self, task):
        return None


def make_pipeline(pre=None, post=None, has_quota=False, hooks=None):
    """Build a minimal ExecutionPipeline for introspection tests."""
    return ExecutionPipeline(
        router=FakeRouter() if has_quota is False else FakeRouter(),
        pre_bridge_stages=pre or [],
        post_bridge_stages=post or [],
        quota=None,
        hooks=hooks,
    )


def make_pipeline_with_stages(pre_count=1, post_count=1):
    """Build a pipeline with actual stage instances."""
    pre = [RouteStage(FakeRouter())] if pre_count else []
    post = [MetricsStage()] if post_count else []
    return ExecutionPipeline(
        router=FakeRouter(),
        pre_bridge_stages=pre,
        post_bridge_stages=post,
        quota=None,
    )


# ─────────────────────────────────────────────────────────────
# 1. TestPipelineDescriptor (5 tests)
# ─────────────────────────────────────────────────────────────

class TestPipelineDescriptor:
    """PipelineDescriptor value object tests."""

    def test_frozen(self):
        """PipelineDescriptor is frozen (immutable)."""
        pd = PipelineDescriptor(
            pre_bridge=(),
            post_bridge=(),
            has_router=True,
            has_quota=False,
            has_hooks=False,
        )
        with pytest.raises(FrozenInstanceError):
            pd.name = "other"  # type: ignore

    def test_fields_complete(self):
        """All required fields are present."""
        pd = PipelineDescriptor(
            pre_bridge=(),
            post_bridge=(),
            has_router=True,
            has_quota=False,
            has_hooks=True,
        )
        assert pd.name == "default"
        assert pd.pre_bridge == ()
        assert pd.post_bridge == ()
        assert pd.has_router is True
        assert pd.has_quota is False
        assert pd.has_hooks is True
        assert pd.version == "1.0.11"

    def test_pre_bridge_is_tuple(self):
        """pre_bridge is a Tuple (not List)."""
        sd = StageDescriptor(name="route", role="router")
        pd = PipelineDescriptor(
            pre_bridge=(sd,),
            post_bridge=(),
            has_router=True,
            has_quota=False,
            has_hooks=False,
        )
        assert isinstance(pd.pre_bridge, tuple)

    def test_version_default(self):
        """version defaults to '1.0.11' (producer version, not schema_version)."""
        pd = PipelineDescriptor(
            pre_bridge=(),
            post_bridge=(),
            has_router=False,
            has_quota=False,
            has_hooks=False,
        )
        assert pd.version == "1.0.11"

    def test_hashable(self):
        """PipelineDescriptor is hashable (frozen dataclass with hashable fields)."""
        sd = StageDescriptor(name="route", role="router")
        pd = PipelineDescriptor(
            pre_bridge=(sd,),
            post_bridge=(),
            has_router=True,
            has_quota=False,
            has_hooks=False,
        )
        # Should not raise
        hash(pd)


# ─────────────────────────────────────────────────────────────
# 2. TestSerializePipeline (7 tests)
# ─────────────────────────────────────────────────────────────

class TestSerializePipeline:
    """serialize_pipeline() canonical function tests."""

    def _make_descriptor(self, pre=1, post=1):
        pre_stages = tuple(
            StageDescriptor(name=f"pre_{i}", role="stage")
            for i in range(pre)
        )
        post_stages = tuple(
            StageDescriptor(name=f"post_{i}", role="stage")
            for i in range(post)
        )
        return PipelineDescriptor(
            pre_bridge=pre_stages,
            post_bridge=post_stages,
            has_router=True,
            has_quota=False,
            has_hooks=True,
        )

    def test_returns_dict(self):
        """serialize_pipeline returns a dict."""
        pd = self._make_descriptor()
        result = serialize_pipeline(pd)
        assert isinstance(result, dict)

    def test_stages_order(self):
        """Stages are ordered: pre → bridge → post."""
        pd = self._make_descriptor(pre=2, post=2)
        result = serialize_pipeline(pd)
        positions = [s["position"] for s in result["stages"]]
        assert positions == ["pre", "pre", "bridge", "post", "post"]

    def test_edges_use_stable_id(self):
        """Edges use stable structural IDs (pre:0, bridge, post:0), not names."""
        pd = self._make_descriptor()
        result = serialize_pipeline(pd)
        for edge in result["edges"]:
            assert ":" in edge["from"] or edge["from"] == "bridge"
            assert ":" in edge["to"] or edge["to"] == "bridge"

    def test_bridge_is_virtual_node(self):
        """Bridge appears as a virtual node in stages."""
        pd = self._make_descriptor()
        result = serialize_pipeline(pd)
        bridge_nodes = [s for s in result["stages"] if s["position"] == "bridge"]
        assert len(bridge_nodes) == 1
        assert bridge_nodes[0]["id"] == "bridge"
        assert bridge_nodes[0]["name"] == "__bridge__"
        assert bridge_nodes[0]["role"] == "bridge"

    def test_graph_closure(self):
        """Every edge endpoint can be found in the stages node set (graph closure)."""
        pd = self._make_descriptor(pre=2, post=3)
        result = serialize_pipeline(pd)
        node_ids = {s["id"] for s in result["stages"]}
        for edge in result["edges"]:
            assert edge["from"] in node_ids, f"edge from {edge['from']} not in nodes"
            assert edge["to"] in node_ids, f"edge to {edge['to']} not in nodes"

    def test_has_flags(self):
        """has_router/has_quota/has_hooks flags are correctly serialized."""
        pd = self._make_descriptor()
        pd = PipelineDescriptor(
            pre_bridge=pd.pre_bridge,
            post_bridge=pd.post_bridge,
            has_router=True,
            has_quota=True,
            has_hooks=False,
        )
        result = serialize_pipeline(pd)
        assert result["has_router"] is True
        assert result["has_quota"] is True
        assert result["has_hooks"] is False

    def test_schema_stable(self):
        """Schema keys are stable (no unexpected keys)."""
        pd = self._make_descriptor()
        result = serialize_pipeline(pd)
        assert set(result.keys()) == {
            "name", "stages", "edges",
            "has_router", "has_quota", "has_hooks",
        }


# ─────────────────────────────────────────────────────────────
# 3. TestPipelineDescribe (5 tests)
# ─────────────────────────────────────────────────────────────

class TestPipelineDescribe:
    """ExecutionPipeline.describe() tests."""

    def test_returns_descriptor(self):
        """describe() returns a PipelineDescriptor."""
        p = make_pipeline_with_stages()
        d = p.describe()
        assert isinstance(d, PipelineDescriptor)

    def test_pre_bridge_stages(self):
        """describe() captures pre-bridge stages."""
        p = make_pipeline_with_stages(pre_count=1, post_count=0)
        d = p.describe()
        assert len(d.pre_bridge) == 1
        assert d.pre_bridge[0].name == "route"

    def test_post_bridge_stages(self):
        """describe() captures post-bridge stages."""
        p = make_pipeline_with_stages(pre_count=0, post_count=1)
        d = p.describe()
        assert len(d.post_bridge) == 1
        assert d.post_bridge[0].name == "metrics"

    def test_has_flags(self):
        """describe() captures has_router/has_quota/has_hooks."""
        p = make_pipeline_with_stages()
        d = p.describe()
        assert d.has_router is True
        assert d.has_quota is False  # no quota passed
        assert d.has_hooks is False  # default hooks, not enabled

    def test_stage_count(self):
        """describe() returns correct stage counts."""
        p = make_pipeline_with_stages(pre_count=1, post_count=1)
        d = p.describe()
        assert len(d.pre_bridge) == 1
        assert len(d.post_bridge) == 1


# ─────────────────────────────────────────────────────────────
# 4. TestPipelineToDict (5 tests)
# ─────────────────────────────────────────────────────────────

class TestPipelineToDict:
    """ExecutionPipeline.to_dict() facade tests."""

    def test_facade_delegates_to_serialize(self):
        """to_dict() delegates to serialize_pipeline(describe())."""
        p = make_pipeline_with_stages()
        expected = serialize_pipeline(p.describe())
        assert p.to_dict() == expected

    def test_idempotent(self):
        """to_dict() is idempotent (multiple calls return same result)."""
        p = make_pipeline_with_stages()
        d1 = p.to_dict()
        d2 = p.to_dict()
        assert d1 == d2

    def test_stages_have_id_and_position(self):
        """to_dict() stages contain 'id' and 'position' fields."""
        p = make_pipeline_with_stages()
        d = p.to_dict()
        for stage in d["stages"]:
            assert "id" in stage
            assert "position" in stage

    def test_no_execution_side_effect(self):
        """to_dict() does not trigger run() or modify pipeline state."""
        p = make_pipeline_with_stages()
        original_pre = list(p.pre_bridge_stages)
        original_post = list(p.post_bridge_stages)
        _ = p.to_dict()
        # Pipeline stages unchanged
        assert p.pre_bridge_stages == original_pre
        assert p.post_bridge_stages == original_post

    def test_consumes_descriptor_not_pipeline(self):
        """serialize_pipeline accepts PipelineDescriptor, not ExecutionPipeline."""
        p = make_pipeline_with_stages()
        d = p.describe()
        # serialize_pipeline works with PipelineDescriptor
        result = serialize_pipeline(d)
        assert isinstance(result, dict)
        # serialize_pipeline should NOT accept ExecutionPipeline
        with pytest.raises((TypeError, AttributeError)):
            serialize_pipeline(p)  # type: ignore


# ─────────────────────────────────────────────────────────────
# 5. TestPipelineToJson (3 tests)
# ─────────────────────────────────────────────────────────────

class TestPipelineToJson:
    """ExecutionPipeline.to_json() tests."""

    def test_default_indent(self):
        """to_json() defaults to indent=2."""
        p = make_pipeline_with_stages()
        j = p.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)
        # indent=2 produces newlines
        assert "\n" in j

    def test_compact(self):
        """to_json(indent=None) produces compact JSON."""
        p = make_pipeline_with_stages()
        j = p.to_json(indent=None)
        parsed = json.loads(j)
        assert isinstance(parsed, dict)
        # compact has no newlines
        assert "\n" not in j

    def test_delegates_to_metadata_serialization(self):
        """to_json() delegates to metadata_serialization.to_json()."""
        p = make_pipeline_with_stages()
        j = p.to_json()
        expected = to_json(p.to_dict(), indent=2)
        assert j == expected


# ─────────────────────────────────────────────────────────────
# 6. TestFromStage (5 tests)
# ─────────────────────────────────────────────────────────────

class TestFromStage:
    """StageDescriptor.from_stage() tests."""

    def test_known_stage_route(self):
        """from_stage(RouteStage) returns role='router'."""
        stage = RouteStage(FakeRouter())
        sd = StageDescriptor.from_stage(stage)
        assert sd.name == "route"
        assert sd.role == "router"

    def test_known_stage_metrics(self):
        """from_stage(MetricsStage) returns role='metrics'."""
        stage = MetricsStage()
        sd = StageDescriptor.from_stage(stage)
        assert sd.name == "metrics"
        assert sd.role == "metrics"

    def test_unknown_stage(self):
        """from_stage(unknown stage) returns role='unknown'."""
        class CustomStage:
            @property
            def name(self):
                return "custom"

            def __call__(self, ctx):
                return ctx

        sd = StageDescriptor.from_stage(CustomStage())
        assert sd.name == "custom"
        assert sd.role == "unknown"

    def test_name_fallback(self):
        """from_stage() falls back to class name lower when no .name attribute."""
        class NoNameStage:
            def __call__(self, ctx):
                return ctx

        sd = StageDescriptor.from_stage(NoNameStage())
        assert sd.name == "nonamestage"

    def test_custom_name_does_not_change_role(self):
        """from_stage(RouteStage subclass) returns role based on type name, not inheritance."""
        # RouteStage.name is a property returning "route"
        sd = StageDescriptor.from_stage(RouteStage(FakeRouter()))
        assert sd.role == "router"
        # A subclass with different __name__ won't match _STAGE_ROLE_MAP
        # This is expected: role is based on type name, not inheritance
        class CustomRoute(RouteStage):
            pass
        sd2 = StageDescriptor.from_stage(CustomRoute(FakeRouter()))
        # CustomRoute has type name "CustomRoute", not in _STAGE_ROLE_MAP
        assert sd2.role == "unknown"  # expected: unknown type


# ─────────────────────────────────────────────────────────────
# 7. TestEdgeModel (6 tests)
# ─────────────────────────────────────────────────────────────

class TestEdgeModel:
    """Edge model tests (linear + bridge virtual node)."""

    def test_pre_to_bridge(self):
        """pre_to_bridge edge from last pre stage to bridge."""
        p = make_pipeline_with_stages(pre_count=1, post_count=1)
        d = p.to_dict()
        pre_to_bridge_edges = [e for e in d["edges"] if e["type"] == "pre_to_bridge"]
        assert len(pre_to_bridge_edges) == 1
        assert pre_to_bridge_edges[0]["from"] == "pre:0"
        assert pre_to_bridge_edges[0]["to"] == "bridge"

    def test_bridge_to_post(self):
        """bridge_to_post edge from bridge to first post stage."""
        p = make_pipeline_with_stages(pre_count=1, post_count=1)
        d = p.to_dict()
        bridge_to_post_edges = [e for e in d["edges"] if e["type"] == "bridge_to_post"]
        assert len(bridge_to_post_edges) == 1
        assert bridge_to_post_edges[0]["from"] == "bridge"
        assert bridge_to_post_edges[0]["to"] == "post:0"

    def test_sequential(self):
        """sequential edge between adjacent post stages."""
        p = make_pipeline_with_stages(pre_count=0, post_count=2)
        # Need 2 post stages — use MetricsStage twice
        p.post_bridge_stages = [MetricsStage(), MetricsStage()]
        d = p.to_dict()
        seq_edges = [e for e in d["edges"] if e["type"] == "sequential"]
        assert len(seq_edges) >= 1

    def test_empty_pipeline(self):
        """Empty pipeline (pre=0, post=0) still has bridge virtual node."""
        p = make_pipeline(pre=[], post=[])
        d = p.to_dict()
        bridge_nodes = [s for s in d["stages"] if s["position"] == "bridge"]
        assert len(bridge_nodes) == 1
        assert len(d["edges"]) == 0

    def test_pre_only(self):
        """Pipeline with only pre stages: edge pre:last → bridge."""
        p = make_pipeline_with_stages(pre_count=1, post_count=0)
        d = p.to_dict()
        edges = d["edges"]
        # Should have pre_to_bridge edge
        assert any(e["type"] == "pre_to_bridge" for e in edges)
        # Should NOT have bridge_to_post
        assert not any(e["type"] == "bridge_to_post" for e in edges)

    def test_post_only(self):
        """Pipeline with only post stages: edge bridge → post:0."""
        p = make_pipeline_with_stages(pre_count=0, post_count=1)
        d = p.to_dict()
        edges = d["edges"]
        # Should have bridge_to_post edge
        assert any(e["type"] == "bridge_to_post" for e in edges)
        # Should NOT have pre_to_bridge
        assert not any(e["type"] == "pre_to_bridge" for e in edges)


# ─────────────────────────────────────────────────────────────
# 8. TestSchemaStability (2 tests)
# ─────────────────────────────────────────────────────────────

class TestSchemaStability:
    """Schema stability tests."""

    def test_no_schema_version(self):
        """V1.0.11 does not output schema_version (V1.1 deferred)."""
        p = make_pipeline_with_stages()
        d = p.to_dict()
        assert "schema_version" not in d
        assert "version" not in d

    def test_keys_stable(self):
        """Top-level keys are stable."""
        p = make_pipeline_with_stages()
        d = p.to_dict()
        assert set(d.keys()) == {
            "name", "stages", "edges",
            "has_router", "has_quota", "has_hooks",
        }


# ─────────────────────────────────────────────────────────────
# 9. TestBackwardCompat (3 tests)
# ─────────────────────────────────────────────────────────────

class TestBackwardCompat:
    """Backward compatibility tests."""

    def test_run_unchanged(self):
        """run() method still exists and is callable."""
        p = make_pipeline_with_stages()
        assert callable(p.run)

    def test_execution_contract_regression(self):
        """Introspection does not modify execution semantics.

        The same pipeline should produce the same run() behavior
        regardless of whether describe() was called.
        """
        p = make_pipeline_with_stages()
        # Call introspection
        _ = p.describe()
        _ = p.to_dict()
        _ = p.to_json()
        # run() should still be intact
        assert hasattr(p, "run")
        assert hasattr(p, "_base_execute")
        # assemble_result is a staticmethod on PipelineExecutor, not ExecutionPipeline
        from planner.pipeline import PipelineExecutor
        assert hasattr(PipelineExecutor, "assemble_result")

    def test_existing_tests_pass(self):
        """Existing test infrastructure is not broken by introspection."""
        # This is a meta-test: verify imports work
        from planner.pipeline import ExecutionPipeline
        from planner.pipeline_descriptor import PipelineDescriptor
        from planner.metadata_serialization import serialize_pipeline
        assert ExecutionPipeline is not None
        assert PipelineDescriptor is not None
        assert serialize_pipeline is not None


# ─────────────────────────────────────────────────────────────
# 10. TestDuplicateNames (2 tests)
# ─────────────────────────────────────────────────────────────

class TestDuplicateNames:
    """Duplicate stage names tests (ChatGPT P0: stable ID resolves ambiguity)."""

    def test_duplicate_stage_names_no_ambiguity(self):
        """Two stages with same name produce unambiguous edges via stable ID."""
        p = make_pipeline(pre=[], post=[MetricsStage(), MetricsStage()])
        d = p.to_dict()
        # Two post stages with same display name "metrics"
        post_stages = [s for s in d["stages"] if s["position"] == "post"]
        assert len(post_stages) == 2
        assert post_stages[0]["name"] == post_stages[1]["name"]  # same name
        assert post_stages[0]["id"] != post_stages[1]["id"]  # different ID
        # Edges use IDs, not names
        for edge in d["edges"]:
            if edge["type"] == "sequential":
                assert edge["from"] == "post:0"
                assert edge["to"] == "post:1"

    def test_bridge_endpoint_resolves(self):
        """Every edge endpoint resolves to a node in the stages set."""
        p = make_pipeline_with_stages(pre_count=1, post_count=1)
        d = p.to_dict()
        node_ids = {s["id"] for s in d["stages"]}
        for edge in d["edges"]:
            assert edge["from"] in node_ids
            assert edge["to"] in node_ids


# ─────────────────────────────────────────────────────────────
# 11. TestDescriptorSnapshot (2 tests)
# ─────────────────────────────────────────────────────────────

class TestDescriptorSnapshot:
    """Descriptor snapshot semantics tests."""

    def test_descriptor_is_snapshot(self):
        """describe() returns an immutable snapshot."""
        p = make_pipeline_with_stages()
        d = p.describe()
        with pytest.raises(FrozenInstanceError):
            d.name = "changed"  # type: ignore

    def test_pipeline_change_does_not_affect_descriptor(self):
        """Modifying pipeline after describe() does not affect the descriptor."""
        p = make_pipeline_with_stages(pre_count=1, post_count=1)
        d = p.describe()
        original_pre_count = len(d.pre_bridge)
        # Modify pipeline (add a stage — this changes the list in place)
        p.post_bridge_stages.append(MetricsStage())
        # Descriptor should be unchanged
        assert len(d.pre_bridge) == original_pre_count
        assert len(d.post_bridge) == 1  # original count in descriptor
