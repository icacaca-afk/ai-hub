# AI Hub — Metadata Serialization Tests (V1.0.10, ADR-0031)
#
# 测试覆盖 ADR-0031 §6.1 的 9 个测试类 (~30 tests)
#
# 测试类:
#   1. TestSerializeDescriptor (6 tests)
#   2. TestSerializeStageInfo (5 tests)
#   3. TestSerializeRuntimeMetadata (5 tests)
#   4. TestSerializeConditionEval (3 tests)
#   5. TestToDictMethods (6 tests)
#   6. TestToJsonHelper (3 tests)
#   7. TestMigrationFromV109 (3 tests)
#   8. TestSchemaStability (2 tests)
#   9. TestRoundTripAndNoMutation (4 tests)

from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any, Dict

import pytest

from planner.metadata_serialization import (
    FUTURE_METADATA_SCHEMA_VERSION,
    serialize_condition_eval,
    serialize_descriptor,
    serialize_runtime_metadata,
    serialize_stage_info,
    to_json,
)
from planner.runtime_metadata import RuntimeMetadata
from planner.stage_descriptor import StageDescriptor
from planner.stage_registry import StageInfo, _descriptor_to_dict, default_registry
from planner.stages.condition_stage import ConditionEval


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def sample_descriptor() -> StageDescriptor:
    return StageDescriptor(
        name="route",
        role="stage",
        version=2,
        capabilities=frozenset({"selects_provider", "routes"}),
        idempotent=True,
        has_side_effects=False,
        always_run_after_stop=False,
        experimental=False,
        description="Routes task to best provider",
        owner="ai-hub",
    )


@pytest.fixture
def sample_stage_info(sample_descriptor: StageDescriptor) -> StageInfo:
    return StageInfo(
        descriptor=sample_descriptor,
        source="builtin",
        requires=("router",),
        registered_at=datetime(2026, 7, 19, 10, 30, 0, 123456),
    )


@pytest.fixture
def sample_condition_eval() -> ConditionEval:
    return ConditionEval(
        stage="condition",
        condition_name="should_stop",
        result=True,
        action="stop",
        timestamp=1234567890.123,
        stopped_by="condition",
    )


@pytest.fixture
def sample_runtime_metadata(sample_condition_eval: ConditionEval) -> RuntimeMetadata:
    rm = RuntimeMetadata()
    rm.server_metrics = {"latency_ms": 42, "status": "ok"}
    rm.condition_eval = sample_condition_eval
    rm.stopped_by = "condition"
    rm.plan = {"success": 3, "failed": 1, "skipped": 0, "total": 4}
    rm.custom = {"plugin_x": {"enabled": True}}
    return rm


# ─────────────────────────────────────────────────────────────
# 1. TestSerializeDescriptor (6 tests)
# ─────────────────────────────────────────────────────────────

class TestSerializeDescriptor:

    def test_serialize_descriptor_returns_dict(self, sample_descriptor: StageDescriptor):
        result = serialize_descriptor(sample_descriptor)
        assert isinstance(result, dict)

    def test_serialize_descriptor_capabilities_sorted(self, sample_descriptor: StageDescriptor):
        result = serialize_descriptor(sample_descriptor)
        assert result["capabilities"] == sorted(["selects_provider", "routes"])

    def test_serialize_descriptor_all_fields_present(self, sample_descriptor: StageDescriptor):
        result = serialize_descriptor(sample_descriptor)
        expected_keys = {
            "name", "role", "version", "capabilities",
            "idempotent", "has_side_effects", "always_run_after_stop",
            "experimental", "description", "owner",
        }
        assert set(result.keys()) == expected_keys

    def test_serialize_descriptor_field_types(self, sample_descriptor: StageDescriptor):
        result = serialize_descriptor(sample_descriptor)
        assert isinstance(result["name"], str)
        assert isinstance(result["role"], str)
        assert isinstance(result["version"], int)
        assert isinstance(result["capabilities"], list)
        assert isinstance(result["idempotent"], bool)
        assert isinstance(result["has_side_effects"], bool)
        assert isinstance(result["always_run_after_stop"], bool)
        assert isinstance(result["experimental"], bool)
        assert isinstance(result["description"], str)
        assert isinstance(result["owner"], str)

    def test_serialize_descriptor_immutable_input(self, sample_descriptor: StageDescriptor):
        original_caps = sample_descriptor.capabilities
        serialize_descriptor(sample_descriptor)
        assert sample_descriptor.capabilities == original_caps

    def test_serialize_descriptor_schema_stable(self, sample_descriptor: StageDescriptor):
        """R4 守护: keys 不变 (V1.0.10 → V1.1 升级时更新)."""
        result = serialize_descriptor(sample_descriptor)
        expected_keys = sorted([
            "name", "role", "version", "capabilities",
            "idempotent", "has_side_effects", "always_run_after_stop",
            "experimental", "description", "owner",
        ])
        assert sorted(result.keys()) == expected_keys


# ─────────────────────────────────────────────────────────────
# 2. TestSerializeStageInfo (5 tests)
# ─────────────────────────────────────────────────────────────

class TestSerializeStageInfo:

    def test_serialize_stage_info_returns_dict(self, sample_stage_info: StageInfo):
        result = serialize_stage_info(sample_stage_info)
        assert isinstance(result, dict)

    def test_serialize_stage_info_includes_descriptor(self, sample_stage_info: StageInfo):
        result = serialize_stage_info(sample_stage_info)
        assert "descriptor" in result
        assert isinstance(result["descriptor"], dict)
        assert result["descriptor"]["name"] == "route"

    def test_serialize_stage_info_registered_at_iso(self, sample_stage_info: StageInfo):
        result = serialize_stage_info(sample_stage_info)
        assert result["registered_at"] == "2026-07-19T10:30:00.123456"

    def test_serialize_stage_info_registered_at_none(self):
        info = StageInfo(
            descriptor=StageDescriptor(name="x"),
            source="test",
            requires=(),
            registered_at=None,  # type: ignore[arg-type]
        )
        result = serialize_stage_info(info)
        assert result["registered_at"] is None

    def test_serialize_stage_info_schema_stable(self, sample_stage_info: StageInfo):
        result = serialize_stage_info(sample_stage_info)
        expected_keys = sorted(["name", "descriptor", "source", "requires", "registered_at"])
        assert sorted(result.keys()) == expected_keys


# ─────────────────────────────────────────────────────────────
# 3. TestSerializeRuntimeMetadata (5 tests)
# ─────────────────────────────────────────────────────────────

class TestSerializeRuntimeMetadata:

    def test_serialize_runtime_metadata_returns_dict(self, sample_runtime_metadata: RuntimeMetadata):
        result = serialize_runtime_metadata(sample_runtime_metadata)
        assert isinstance(result, dict)

    def test_serialize_runtime_metadata_condition_eval_none(self):
        rm = RuntimeMetadata()
        result = serialize_runtime_metadata(rm)
        assert result["condition_eval"] is None

    def test_serialize_runtime_metadata_condition_eval_present(
        self, sample_runtime_metadata: RuntimeMetadata
    ):
        result = serialize_runtime_metadata(sample_runtime_metadata)
        assert result["condition_eval"] is not None
        assert result["condition_eval"]["condition_name"] == "should_stop"

    def test_serialize_runtime_metadata_custom_namespace(self):
        rm = RuntimeMetadata()
        rm.custom = {"my_plugin": {"enabled": True, "count": 5}}
        result = serialize_runtime_metadata(rm)
        assert result["custom"] == {"my_plugin": {"enabled": True, "count": 5}}

    def test_serialize_runtime_metadata_schema_stable(self, sample_runtime_metadata: RuntimeMetadata):
        result = serialize_runtime_metadata(sample_runtime_metadata)
        expected_keys = sorted([
            "server_metrics", "condition_eval", "stopped_by", "plan", "custom",
        ])
        assert sorted(result.keys()) == expected_keys


# ─────────────────────────────────────────────────────────────
# 4. TestSerializeConditionEval (3 tests)
# ─────────────────────────────────────────────────────────────

class TestSerializeConditionEval:

    def test_serialize_condition_eval_returns_dict(self, sample_condition_eval: ConditionEval):
        result = serialize_condition_eval(sample_condition_eval)
        assert isinstance(result, dict)

    def test_serialize_condition_eval_all_fields(self, sample_condition_eval: ConditionEval):
        result = serialize_condition_eval(sample_condition_eval)
        assert result["stage"] == "condition"
        assert result["condition_name"] == "should_stop"
        assert result["result"] is True
        assert result["action"] == "stop"
        assert result["timestamp"] == 1234567890.123
        assert result["stopped_by"] == "condition"

    def test_serialize_condition_eval_backward_compat(self, sample_condition_eval: ConditionEval):
        """V1.0.4 ConditionEval.to_dict() must match V1.0.10 serialize_condition_eval."""
        assert sample_condition_eval.to_dict() == serialize_condition_eval(sample_condition_eval)


# ─────────────────────────────────────────────────────────────
# 5. TestToDictMethods (6 tests)
# ─────────────────────────────────────────────────────────────

class TestToDictMethods:

    def test_stage_descriptor_to_dict(self, sample_descriptor: StageDescriptor):
        result = sample_descriptor.to_dict()
        assert result == serialize_descriptor(sample_descriptor)

    def test_stage_info_to_dict(self, sample_stage_info: StageInfo):
        result = sample_stage_info.to_dict()
        assert result == serialize_stage_info(sample_stage_info)

    def test_runtime_metadata_to_dict(self, sample_runtime_metadata: RuntimeMetadata):
        result = sample_runtime_metadata.to_dict()
        assert result == serialize_runtime_metadata(sample_runtime_metadata)

    def test_condition_eval_to_dict(self, sample_condition_eval: ConditionEval):
        result = sample_condition_eval.to_dict()
        assert result == serialize_condition_eval(sample_condition_eval)

    def test_to_dict_delegates_to_serialize(
        self,
        sample_descriptor: StageDescriptor,
        sample_stage_info: StageInfo,
        sample_runtime_metadata: RuntimeMetadata,
        sample_condition_eval: ConditionEval,
    ):
        """R1: to_dict() is facade, must equal canonical serialize_xxx()."""
        assert sample_descriptor.to_dict() == serialize_descriptor(sample_descriptor)
        assert sample_stage_info.to_dict() == serialize_stage_info(sample_stage_info)
        assert sample_runtime_metadata.to_dict() == serialize_runtime_metadata(sample_runtime_metadata)
        assert sample_condition_eval.to_dict() == serialize_condition_eval(sample_condition_eval)

    def test_to_dict_methods_idempotent(self, sample_descriptor: StageDescriptor):
        d1 = sample_descriptor.to_dict()
        d2 = sample_descriptor.to_dict()
        assert d1 == d2


# ─────────────────────────────────────────────────────────────
# 6. TestToJsonHelper (3 tests)
# ─────────────────────────────────────────────────────────────

class TestToJsonHelper:

    def test_to_json_default_indent(self, sample_descriptor: StageDescriptor):
        d = serialize_descriptor(sample_descriptor)
        s = to_json(d)
        assert isinstance(s, str)
        assert '\n' in s  # default indent=2 produces newlines

    def test_to_json_compact(self, sample_descriptor: StageDescriptor):
        d = serialize_descriptor(sample_descriptor)
        s = to_json(d, indent=None)
        assert '\n' not in s

    def test_to_json_ensure_ascii_false(self):
        d = {"name": "测试", "value": 42}
        s = to_json(d)
        assert "测试" in s  # not escaped


# ─────────────────────────────────────────────────────────────
# 7. TestMigrationFromV109 (3 tests)
# ─────────────────────────────────────────────────────────────

class TestMigrationFromV109:

    def test_descriptor_to_dict_alias_delegates(self, sample_descriptor: StageDescriptor):
        """V1.0.9 _descriptor_to_dict helper delegates to V1.0.10 serialize_descriptor."""
        assert _descriptor_to_dict(sample_descriptor) == serialize_descriptor(sample_descriptor)

    def test_stage_registry_to_dict_uses_serialize_stage_info(self):
        """V1.0.10: StageRegistry.to_dict() uses serialize_stage_info (schema 不变)."""
        registry = default_registry()
        result = registry.to_dict()
        assert isinstance(result, dict)
        assert "stages" in result
        assert all(isinstance(s, dict) for s in result["stages"])

    def test_stage_registry_to_dict_schema_stable(self):
        """R4: StageRegistry.to_dict() schema 不变 (V1.0.9 → V1.0.10)."""
        registry = default_registry()
        result = registry.to_dict()
        expected_top_keys = sorted(["stages", "roles", "capabilities", "default_order"])
        assert sorted(result.keys()) == expected_top_keys
        if result["stages"]:
            stage_keys = sorted(result["stages"][0].keys())
            expected_stage_keys = sorted(["name", "descriptor", "source", "requires", "registered_at"])
            assert stage_keys == expected_stage_keys


# ─────────────────────────────────────────────────────────────
# 8. TestSchemaStability (2 tests)
# ─────────────────────────────────────────────────────────────

class TestSchemaStability:

    def test_metadata_schema_version_none_v1010(self):
        """V1.0.10: FUTURE_METADATA_SCHEMA_VERSION is None (V1.1 启用)."""
        assert FUTURE_METADATA_SCHEMA_VERSION is None

    def test_no_schema_version_in_v1010_output(self, sample_descriptor: StageDescriptor):
        """V1.0.10: serialize output 不含 schema_version key."""
        d = serialize_descriptor(sample_descriptor)
        assert "schema_version" not in d


# ─────────────────────────────────────────────────────────────
# 9. TestRoundTripAndNoMutation (4 tests, R4 采纳 ChatGPT Q8 建议)
# ─────────────────────────────────────────────────────────────

class TestRoundTripAndNoMutation:

    def test_json_round_trip_descriptor(self, sample_descriptor: StageDescriptor):
        d = serialize_descriptor(sample_descriptor)
        s = to_json(d)
        assert json.loads(s) == d

    def test_json_round_trip_stage_info(self, sample_stage_info: StageInfo):
        d = serialize_stage_info(sample_stage_info)
        s = to_json(d)
        assert json.loads(s) == d

    def test_json_round_trip_runtime_metadata(self, sample_runtime_metadata: RuntimeMetadata):
        d = serialize_runtime_metadata(sample_runtime_metadata)
        s = to_json(d)
        assert json.loads(s) == d

    def test_no_mutation_property(self, sample_runtime_metadata: RuntimeMetadata):
        """序列化不修改原 dataclass."""
        before = copy.deepcopy(sample_runtime_metadata)
        serialize_runtime_metadata(sample_runtime_metadata)
        assert sample_runtime_metadata == before
