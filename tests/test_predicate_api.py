"""V1.0.12 Predicate API contract tests (ADR-0033)."""

from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest

from planner.metadata_serialization import serialize_predicate
from planner.predicate_descriptor import PredicateDescriptor
from planner.stages import ConditionStage


class TestPredicateDescriptor:
    def test_fields(self):
        pd = PredicateDescriptor("ok", "successful", "bridge_result.success")
        assert (pd.name, pd.description, pd.subject) == (
            "ok", "successful", "bridge_result.success"
        )

    def test_defaults(self):
        assert PredicateDescriptor("ok") == PredicateDescriptor("ok", "", "")

    def test_frozen(self):
        pd = PredicateDescriptor("ok")
        with pytest.raises(FrozenInstanceError):
            pd.name = "changed"  # type: ignore[misc]

    def test_hashable(self):
        assert PredicateDescriptor("ok") in {PredicateDescriptor("ok")}

    def test_to_dict_round_trip(self):
        pd = PredicateDescriptor("ok", "successful", "result.success")
        assert pd.to_dict() == serialize_predicate(pd)


class TestSerializePredicate:
    def test_returns_dict(self):
        assert isinstance(serialize_predicate(PredicateDescriptor("ok")), dict)

    def test_schema_keys_stable(self):
        assert set(serialize_predicate(PredicateDescriptor("ok"))) == {
            "name", "description", "subject"
        }

    def test_empty_description_subject(self):
        assert serialize_predicate(PredicateDescriptor("ok")) == {
            "name": "ok", "description": "", "subject": ""
        }

    def test_values_preserved(self):
        pd = PredicateDescriptor("失败检查", "检查结果", "bridge_result.success")
        assert serialize_predicate(pd)["description"] == "检查结果"


class TestDescribePredicate:
    def test_returns_descriptor(self):
        stage = ConditionStage(lambda ctx: True)
        assert isinstance(stage.describe_predicate(), PredicateDescriptor)

    def test_explicit_name(self):
        stage = ConditionStage(lambda ctx: True, predicate_name="on_success")
        assert stage.describe_predicate().name == "on_success"

    def test_named_function_fallback(self):
        def bridge_succeeded(ctx):
            return True

        assert ConditionStage(bridge_succeeded).describe_predicate().name == "bridge_succeeded"

    def test_lambda_fallback(self):
        assert ConditionStage(lambda ctx: True).describe_predicate().name == "condition"

    def test_explicit_description_subject(self):
        pd = ConditionStage(
            lambda ctx: True,
            predicate_description="Bridge completed successfully",
            predicate_subject="bridge_result.success",
        ).describe_predicate()
        assert (pd.description, pd.subject) == (
            "Bridge completed successfully", "bridge_result.success"
        )

    def test_no_evaluation_side_effect(self):
        calls = []

        def predicate(ctx):
            calls.append(ctx)
            return True

        ConditionStage(predicate).describe_predicate()
        assert calls == []


class TestNoIntrospection:
    def test_no_inspect_getsource(self):
        with patch("inspect.getsource", side_effect=AssertionError("forbidden")):
            ConditionStage(lambda ctx: True).describe_predicate()

    def test_no_ast_parse(self):
        with patch("ast.parse", side_effect=AssertionError("forbidden")):
            ConditionStage(lambda ctx: True).describe_predicate()

    def test_no_dis_disassemble(self):
        with patch("dis.dis", side_effect=AssertionError("forbidden")):
            ConditionStage(lambda ctx: True).describe_predicate()


class TestBackwardCompat:
    def test_existing_constructor_unchanged(self):
        condition = lambda ctx: True
        stage = ConditionStage(condition, "skip", "abort", "legacy")
        assert (stage.condition, stage.on_true, stage.on_false, stage.name) == (
            condition, "skip", "abort", "legacy"
        )

    def test_new_defaults_are_empty(self):
        stage = ConditionStage(lambda ctx: True)
        assert (stage.predicate_name, stage.predicate_description, stage.predicate_subject) == (
            None, "", ""
        )

    def test_export_from_stages(self):
        from planner.stages import PredicateDescriptor as Exported

        assert Exported is PredicateDescriptor

    def test_pipeline_serialization_not_changed(self):
        from planner.metadata_serialization import serialize_pipeline
        from planner.pipeline_descriptor import PipelineDescriptor

        result = serialize_pipeline(PipelineDescriptor((), (), False, False, False))
        assert set(result) == {
            "name", "stages", "edges", "has_router", "has_quota", "has_hooks"
        }
