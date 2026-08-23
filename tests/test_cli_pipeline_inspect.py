"""V1.0.13 CLI pipeline introspection tests (ADR-0034)."""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest

from planner.pipeline import ExecutionPipeline
from planner.stages import ConditionStage


class _NoExecuteRouter:
    def route(self, task):
        raise AssertionError("pipeline introspection must not route or execute")


def _pipeline_with_predicates() -> ExecutionPipeline:
    pre = ConditionStage(
        lambda ctx: True,
        name="duplicate",
        predicate_name="request_allowed",
        predicate_description="Allow an eligible request",
        predicate_subject="task.capabilities",
    )
    post = ConditionStage(
        lambda ctx: True,
        name="duplicate",
        predicate_name="bridge_succeeded",
        predicate_description="Continue after a successful bridge call",
        predicate_subject="bridge_result.success",
    )
    return ExecutionPipeline(
        router=_NoExecuteRouter(),
        pre_bridge_stages=[pre],
        post_bridge_stages=[post],
    )


class TestBuildPipelineInspection:
    def test_top_level_schema(self):
        from cli.pipeline_inspect import build_pipeline_inspection

        payload = build_pipeline_inspection(_pipeline_with_predicates())
        assert set(payload) == {"runtime_version", "pipeline", "predicates"}
        assert payload["runtime_version"] == "1.0.13"

    def test_pipeline_is_canonical_document(self):
        from cli.pipeline_inspect import build_pipeline_inspection

        pipeline = _pipeline_with_predicates()
        assert build_pipeline_inspection(pipeline)["pipeline"] == pipeline.to_dict()

    def test_predicates_use_stable_ids_in_pipeline_order(self):
        from cli.pipeline_inspect import build_pipeline_inspection

        rows = build_pipeline_inspection(_pipeline_with_predicates())["predicates"]
        assert rows == [
            {
                "stage_id": "pre:0",
                "predicate": {
                    "name": "request_allowed",
                    "description": "Allow an eligible request",
                    "subject": "task.capabilities",
                },
            },
            {
                "stage_id": "post:0",
                "predicate": {
                    "name": "bridge_succeeded",
                    "description": "Continue after a successful bridge call",
                    "subject": "bridge_result.success",
                },
            },
        ]

    def test_duplicate_stage_names_remain_unambiguous(self):
        from cli.pipeline_inspect import build_pipeline_inspection

        rows = build_pipeline_inspection(_pipeline_with_predicates())["predicates"]
        assert [row["stage_id"] for row in rows] == ["pre:0", "post:0"]

    def test_pipeline_without_predicates_returns_empty_list(self):
        from cli.pipeline_inspect import build_pipeline_inspection

        pipeline = ExecutionPipeline(router=_NoExecuteRouter())
        assert build_pipeline_inspection(pipeline)["predicates"] == []


class TestInspectionSafety:
    def test_predicate_is_not_evaluated(self):
        from cli.pipeline_inspect import build_pipeline_inspection

        calls = []

        def predicate(ctx):
            calls.append(ctx)
            return True

        pipeline = ExecutionPipeline(
            router=_NoExecuteRouter(),
            post_bridge_stages=[ConditionStage(predicate, predicate_name="safe")],
        )
        build_pipeline_inspection(pipeline)
        assert calls == []

    def test_pipeline_run_is_not_called(self):
        from cli.pipeline_inspect import build_pipeline_inspection

        pipeline = _pipeline_with_predicates()
        with patch.object(
            pipeline, "run", side_effect=AssertionError("run is forbidden")
        ):
            build_pipeline_inspection(pipeline)

    def test_source_ast_and_bytecode_are_not_inspected(self):
        from cli.pipeline_inspect import build_pipeline_inspection

        pipeline = _pipeline_with_predicates()
        with (
            patch("inspect.getsource", side_effect=AssertionError("forbidden")),
            patch("ast.parse", side_effect=AssertionError("forbidden")),
            patch("dis.dis", side_effect=AssertionError("forbidden")),
        ):
            build_pipeline_inspection(pipeline)


class TestPipelineCommand:
    def test_json_output_contains_json_only(self, capsys):
        from cli.pipeline_inspect import cmd_pipeline

        cmd_pipeline(["inspect", "--json"], pipeline=_pipeline_with_predicates())
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["runtime_version"] == "1.0.13"
        assert captured.err == ""

    def test_human_output_has_stages_predicates_and_edges(self, capsys):
        from cli.pipeline_inspect import cmd_pipeline

        cmd_pipeline(["inspect"], pipeline=_pipeline_with_predicates())
        out = capsys.readouterr().out
        assert "AI Hub Pipeline — v1.0.13" in out
        assert "[pre:0] duplicate (condition)" in out
        assert "[post:0] bridge_succeeded" in out
        assert "bridge_result.success" in out
        assert "pre:0 -> bridge" in out

    def test_empty_predicates_are_explicit(self, capsys):
        from cli.pipeline_inspect import cmd_pipeline

        pipeline = ExecutionPipeline(router=_NoExecuteRouter())
        cmd_pipeline(["inspect"], pipeline=pipeline)
        assert "(none declared)" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "args",
        [
            [],
            ["unknown"],
            ["inspect", "--bad"],
            ["inspect", "--json", "--json"],
        ],
    )
    def test_invalid_arguments_exit_one(self, args, capsys):
        from cli.pipeline_inspect import cmd_pipeline

        with pytest.raises(SystemExit) as exc:
            cmd_pipeline(args, pipeline=_pipeline_with_predicates())
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Usage: ai-hub pipeline inspect [--json]" in captured.out + captured.err

    def test_help_exits_zero_without_building_pipeline(self, capsys):
        from cli.pipeline_inspect import cmd_pipeline

        cmd_pipeline(["inspect", "--help"])
        assert "Usage: ai-hub pipeline inspect [--json]" in capsys.readouterr().out


class TestMainRegistration:
    def test_main_dispatches_pipeline_arguments(self, monkeypatch):
        import cli.main as main_module

        calls = []
        monkeypatch.setattr(main_module, "cmd_pipeline", lambda args: calls.append(args))
        monkeypatch.setattr(
            sys, "argv", ["ai-hub", "pipeline", "inspect", "--json"]
        )
        main_module.main()
        assert calls == [["inspect", "--json"]]

    def test_main_help_lists_pipeline_inspect(self, monkeypatch, capsys):
        import cli.main as main_module

        monkeypatch.setattr(sys, "argv", ["ai-hub"])
        with pytest.raises(SystemExit) as exc:
            main_module.main()
        assert exc.value.code == 0
        assert "ai-hub pipeline inspect" in capsys.readouterr().out


class TestDefaultPipelineShape:
    """V1.0.13 审核 P1：introspection 必须描述 plan 实际运行的默认 Pipeline。"""

    def test_inspection_matches_plan_executor_default_pipeline(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)  # 持久产物（quota.db 等）落在临时目录
        from cli.pipeline_inspect import _build_default_pipeline
        from cli.pipeline_inspect import build_pipeline_inspection
        from cli.plan import _EVENT_BUS, _PLAN_STORE
        from cli.provider_registry import build_default_registry
        from core.health_registry import HealthRegistry
        from core.quota import QuotaManager
        from planner.executor import PlanExecutor
        from planner.rule_based_planner import RuleBasedPlanner
        from router.metrics_router import MetricsRouter

        quota = QuotaManager()
        router = MetricsRouter(
            build_default_registry(), quota_manager=quota, health_registry=HealthRegistry()
        )
        executor = PlanExecutor(
            router=router,
            planner=RuleBasedPlanner(),
            plan_store=_PLAN_STORE,
            event_bus=_EVENT_BUS,
        )
        reference = build_pipeline_inspection(executor.pipeline)["pipeline"]
        reported = build_pipeline_inspection(_build_default_pipeline())["pipeline"]

        assert reported == reference
        # cmd_plan 的 PlanExecutor 默认不传 quota，introspection 不得失真为 true
        assert reported["has_quota"] is False


class TestInspectSideEffects:
    """V1.0.13 审核 P1："只读 introspection"不得在磁盘留下持久状态。"""

    def _run_isolated(self, tmp_path, *argv):
        import os
        import subprocess
        from pathlib import Path

        root = str(Path(__file__).resolve().parents[1])
        env = dict(os.environ, PYTHONPATH=root)
        return subprocess.run(
            [sys.executable, *argv],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_importing_main_creates_no_persistent_state(self, tmp_path):
        proc = self._run_isolated(tmp_path, "-c", "import cli.main")
        assert proc.returncode == 0, proc.stderr
        assert not (tmp_path / ".ai-hub").exists()

    def test_pipeline_inspect_creates_no_persistent_state(self, tmp_path):
        proc = self._run_isolated(
            tmp_path, "-m", "cli.main", "pipeline", "inspect", "--json"
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["pipeline"]["has_quota"] is False
        assert not (tmp_path / ".ai-hub").exists(), (
            "pipeline inspect must not create .ai-hub/*.db"
        )
