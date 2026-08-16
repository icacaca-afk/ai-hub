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
    predicates.extend(_collect_predicates(pipeline.post_bridge_stages, "post"))
    return {
        "runtime_version": RUNTIME_VERSION,
        "pipeline": pipeline.to_dict(),
        "predicates": predicates,
    }


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


def _print_usage() -> None:
    print(USAGE)


def cmd_pipeline(args: list[str], *, pipeline=None) -> None:
    """Handle ``ai-hub pipeline inspect [--json]``."""
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
    if options.count("--json") > 1:
        print("Option may be specified only once: --json", file=sys.stderr)
        _print_usage()
        raise SystemExit(1)

    selected_pipeline = pipeline if pipeline is not None else _build_default_pipeline()
    payload = build_pipeline_inspection(selected_pipeline)
    if "--json" in options:
        print(to_json(payload, indent=2))
    else:
        _print_human(payload)


__all__ = ["RUNTIME_VERSION", "build_pipeline_inspection", "cmd_pipeline"]
