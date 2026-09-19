# CLI Pipeline Introspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a side-effect-free `ai-hub pipeline inspect [--json]` command that presents canonical pipeline structure and explicitly declared predicate semantics without changing planner schemas.

**Architecture:** `cli/pipeline_inspect.py` owns a presentation-only wrapper around `ExecutionPipeline.to_dict()` and `ConditionStage.describe_predicate()`. Predicate associations remain outside the canonical pipeline document and use ADR-0032 stable stage IDs; `cli/main.py` only registers the nested command and help text.

**Tech Stack:** Python 3.11+, pytest 8, existing `planner` descriptors/serializers, existing flat CLI dispatcher.

---

## File structure

- Create `cli/pipeline_inspect.py`: pure presentation builder, default pipeline factory, human/JSON renderer, and nested command parser.
- Modify `cli/main.py`: import `cmd_pipeline`, add one help line, and register the `pipeline` command.
- Create `tests/test_cli_pipeline_inspect.py`: presentation schema, safety invariants, rendering, parsing, and main-dispatch tests.
- Modify `docs/adr/0034-cli-pipeline-introspection.md`: change status only after external review is recorded.
- Modify `docs/ROADMAP.md` and `docs/ROADMAP.zh-CN.md`: mark V1.0.13 implemented only after tests and review pass.

Frozen files under `core/`, existing routers, and `providers/` are not modified.

## Prerequisites

1. Merge or explicitly defer PR #3 before implementation. That PR also changes
   `cli/main.py`, so this branch must be rebased onto the resulting `master`
   before Task 1.
2. Complete the V1.0.12 Predicate API code-review gate. V1.0.13 consumes that
   API and must not tag a release on top of an unapproved dependency.
3. Record external review of ADR-0034 and resolve every blocking condition
   before creating implementation commits.

### Task 1: Lock the presentation contract with failing tests

**Files:**
- Create: `tests/test_cli_pipeline_inspect.py`
- Reference: `tests/test_pipeline_introspection.py`
- Reference: `tests/test_predicate_api.py`

- [ ] **Step 1: Add deterministic pipeline fixtures**

Create the test module with imports and a router stub that fails if execution is attempted:

```python
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
```

- [ ] **Step 2: Add presentation schema tests**

Append:

```python
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
```

- [ ] **Step 3: Add safety-invariant tests**

Append:

```python
class TestInspectionSafety:
    def test_predicate_is_not_evaluated(self):
        from cli.pipeline_inspect import build_pipeline_inspection

        calls = []

        def predicate(ctx):
            calls.append(ctx)
            return True

        pipeline = ExecutionPipeline(
            router=_NoExecuteRouter(),
            post_bridge_stages=[
                ConditionStage(predicate, predicate_name="safe")
            ],
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
```

- [ ] **Step 4: Run the contract tests and verify the intended failure**

Run:

```powershell
python -m pytest tests/test_cli_pipeline_inspect.py -q
```

Expected: collection succeeds and tests fail with
`ModuleNotFoundError: No module named 'cli.pipeline_inspect'`.

- [ ] **Step 5: Commit the red tests**

```powershell
git add tests/test_cli_pipeline_inspect.py
git commit -m "test: define CLI pipeline introspection contract"
```

### Task 2: Implement the pure presentation builder

**Files:**
- Create: `cli/pipeline_inspect.py`
- Test: `tests/test_cli_pipeline_inspect.py`

- [ ] **Step 1: Add the builder and predicate association helper**

Create `cli/pipeline_inspect.py` with:

```python
"""CLI presentation for side-effect-free pipeline introspection."""

from __future__ import annotations

import sys
from typing import Any

from planner.metadata_serialization import serialize_predicate, to_json

RUNTIME_VERSION = "1.0.13"
USAGE = "Usage: ai-hub pipeline inspect [--json]"


def _collect_predicates(stages: list, position: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, stage in enumerate(stages):
        describe = getattr(stage, "describe_predicate", None)
        if not callable(describe):
            continue
        rows.append(
            {
                "stage_id": f"{position}:{index}",
                "predicate": serialize_predicate(describe()),
            }
        )
    return rows


def build_pipeline_inspection(pipeline) -> dict[str, Any]:
    """Build a CLI document without executing or mutating the pipeline."""
    predicates = _collect_predicates(pipeline.pre_bridge_stages, "pre")
    predicates.extend(
        _collect_predicates(pipeline.post_bridge_stages, "post")
    )
    return {
        "runtime_version": RUNTIME_VERSION,
        "pipeline": pipeline.to_dict(),
        "predicates": predicates,
    }
```

- [ ] **Step 2: Run builder and safety tests**

Run:

```powershell
python -m pytest tests/test_cli_pipeline_inspect.py `
  -k "BuildPipelineInspection or InspectionSafety" -q
```

Expected: 8 tests pass.

- [ ] **Step 3: Run existing planner introspection contracts**

Run:

```powershell
python -m pytest tests/test_pipeline_introspection.py `
  tests/test_predicate_api.py -q
```

Expected: 67 tests pass (45 pipeline + 22 predicate).

- [ ] **Step 4: Commit the pure builder**

```powershell
git add cli/pipeline_inspect.py
git commit -m "V1.0.13: add pipeline inspection presentation model"
```

### Task 3: Add human/JSON rendering and command parsing

**Files:**
- Modify: `cli/pipeline_inspect.py`
- Modify: `tests/test_cli_pipeline_inspect.py`

- [ ] **Step 1: Add rendering and parser tests**

Append to the test file:

```python
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

    @pytest.mark.parametrize("args", [[], ["unknown"], ["inspect", "--bad"]])
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
```

- [ ] **Step 2: Implement the current default pipeline factory**

Append to `cli/pipeline_inspect.py`:

```python
def _build_default_pipeline():
    """Construct the planning CLI's default pipeline without executing it."""
    from cli.plan import _build_registry
    from core.health_registry import HealthRegistry
    from core.quota import QuotaManager
    from planner.pipeline import default_pipeline
    from router.metrics_router import MetricsRouter

    quota = QuotaManager()
    router = MetricsRouter(
        _build_registry(),
        quota_manager=quota,
        health_registry=HealthRegistry(),
    )
    return default_pipeline(router, quota=quota)
```

- [ ] **Step 3: Implement deterministic human rendering**

Append:

```python
def _print_human(payload: dict[str, Any]) -> None:
    pipeline = payload["pipeline"]
    print(f"AI Hub Pipeline — v{payload['runtime_version']}")
    print()
    print(f"Pipeline: {pipeline['name']}")
    print(f"Router: {'configured' if pipeline['has_router'] else 'not configured'}")
    print(f"Quota: {'configured' if pipeline['has_quota'] else 'not configured'}")
    print(f"Hooks: {'enabled' if pipeline['has_hooks'] else 'disabled'}")
    print()
    print("Stages:")
    for stage in pipeline["stages"]:
        print(f"  [{stage['id']}] {stage['name']} ({stage['role']})")
    print()
    print("Predicates:")
    if not payload["predicates"]:
        print("  (none declared)")
    for row in payload["predicates"]:
        predicate = row["predicate"]
        print(f"  [{row['stage_id']}] {predicate['name']}")
        if predicate["subject"]:
            print(f"    Subject: {predicate['subject']}")
        if predicate["description"]:
            print(f"    Description: {predicate['description']}")
    print()
    print("Edges:")
    if not pipeline["edges"]:
        print("  (none)")
    for edge in pipeline["edges"]:
        print(f"  {edge['from']} -> {edge['to']} ({edge['type']})")
```

- [ ] **Step 4: Implement exact command parsing**

Append:

```python
def _print_usage() -> None:
    print(USAGE)


def cmd_pipeline(args: list[str], *, pipeline=None) -> None:
    """Handle `ai-hub pipeline inspect [--json]`."""
    if args in (["--help"], ["inspect", "--help"]):
        _print_usage()
        return
    if not args:
        _print_usage()
        raise SystemExit(1)
    if args[0] != "inspect":
        print(f"Unknown pipeline command: {args[0]}", file=sys.stderr)
        _print_usage()
        raise SystemExit(1)

    options = args[1:]
    unknown = [option for option in options if option != "--json"]
    if unknown:
        print(f"Unknown option: {unknown[0]}", file=sys.stderr)
        _print_usage()
        raise SystemExit(1)

    selected_pipeline = pipeline if pipeline is not None else _build_default_pipeline()
    payload = build_pipeline_inspection(selected_pipeline)
    if "--json" in options:
        print(to_json(payload, indent=2))
    else:
        _print_human(payload)


__all__ = ["RUNTIME_VERSION", "build_pipeline_inspection", "cmd_pipeline"]
```

- [ ] **Step 5: Run the command-module tests**

Run:

```powershell
python -m pytest tests/test_cli_pipeline_inspect.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit rendering and parsing**

```powershell
git add cli/pipeline_inspect.py tests/test_cli_pipeline_inspect.py
git commit -m "V1.0.13: render pipeline inspection in CLI"
```

### Task 4: Register the nested command in the main CLI

**Files:**
- Modify: `cli/main.py`
- Modify: `tests/test_cli_pipeline_inspect.py`

- [ ] **Step 1: Add main-dispatch tests**

Append:

```python
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
```

- [ ] **Step 2: Verify registration tests fail**

Run:

```powershell
python -m pytest tests/test_cli_pipeline_inspect.py::TestMainRegistration -q
```

Expected: failures show `cmd_pipeline` is not imported or registered.

- [ ] **Step 3: Register the command**

In `cli/main.py`, add the import with the other CLI command imports:

```python
from cli.pipeline_inspect import cmd_pipeline
```

Add this usage line before the existing Plan inspection lines:

```python
print('  ai-hub pipeline inspect [--json]  Inspect the default runtime pipeline')
```

Add this entry to `commands`:

```python
"pipeline": cmd_pipeline,
```

- [ ] **Step 4: Run registration and focused feature tests**

Run:

```powershell
python -m pytest tests/test_cli_pipeline_inspect.py `
  tests/test_pipeline_introspection.py tests/test_predicate_api.py -q
```

Expected: all feature and dependency tests pass.

- [ ] **Step 5: Smoke-test the installed command path**

Run:

```powershell
python -m cli.main pipeline inspect --json
python -m cli.main pipeline inspect
```

Expected: the first command prints one valid JSON document; the second prints
the heading plus Pipeline, Stages, Predicates, and Edges sections. Neither
command invokes a Provider.

- [ ] **Step 6: Commit main registration**

```powershell
git add cli/main.py tests/test_cli_pipeline_inspect.py
git commit -m "V1.0.13: register pipeline inspect command"
```

### Task 5: Regression, documentation, and review gate

**Files:**
- Modify: `docs/adr/0034-cli-pipeline-introspection.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/ROADMAP.zh-CN.md`

- [ ] **Step 1: Run whitespace and frozen-boundary checks**

Run:

```powershell
git diff --check origin/master...HEAD
python -m pytest tests/test_provider_contract.py::test_zero_modification_kpi -q
```

Expected: no diff errors and the frozen-boundary test passes.

- [ ] **Step 2: Run the full non-live regression suite**

Run:

```powershell
python -m pytest tests -x -q `
  --deselect tests/test_benchmark.py `
  --deselect tests/test_cli_plan_json.py
```

Expected: zero failures. Record the exact passed/skipped counts in the code
review artifact and commit message notes.

- [ ] **Step 3: Update maintained English and Chinese roadmaps together**

Change the V1.0.13 row in both files from planned to implemented/review pending.
Use these meanings exactly:

```text
Deliverable: `ai-hub pipeline inspect [--json]` with presentation-only predicate joins
Status: Implemented; review pending
```

Do not mark the feature released before the tag and external code review.

- [ ] **Step 4: Record architecture review outcome in ADR-0034**

After external review, replace `Status | Proposed` with the exact reviewed
status and add the score/conditions supplied by the reviewer. If any blocking
condition remains, keep implementation untagged until it is resolved and
covered by a regression test.

- [ ] **Step 5: Commit documentation and review fixes**

```powershell
git add docs/adr/0034-cli-pipeline-introspection.md `
  docs/ROADMAP.md docs/ROADMAP.zh-CN.md
git commit -m "V1.0.13: document CLI pipeline introspection"
```

- [ ] **Step 6: Tag only after code review approval**

```powershell
git tag v1.0.13
git push origin HEAD
git push origin v1.0.13
```

Expected: the branch and release point contain the approved ADR,
implementation, tests, and synchronized bilingual roadmap updates.
