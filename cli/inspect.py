# AI Hub — CLI inspect
# V0.9.3: Plan 事后查看命令
# V0.9.4: + "Trace: Available/No Trace" 关联（ADR-0017 D5 ChatGPT 强建议）
#
# 用法：
#   ai-hub inspect <plan_id>           人类可读
#   ai-hub inspect <plan_id> --json    JSON 输出
#   ai-hub inspect --list              列出最近 N 个 plan
#   ai-hub inspect --list --json       JSON 列表
#
# 数据来源：进程内 PlanStore（环形缓冲 N=10，V0.9.3）。
# ⚠️ **Current Process Only**（ChatGPT 审核建议）：不持久化，进程退出后丢失。
# 跨进程持久化由 V0.9.5+ Execution History 引入。
#
# 与 trace 的职责区分（V0.9.4 ADR-0017 D5）：
#   - inspect: 答「发生了什么？」 → PlanStore（业务）
#   - trace:   答「怎么发生的？」 → TraceCollector（过程）
# V0.9.4 inspect 增加 "Trace: Available/No Trace" 关联提示。
#
# 与 explain-route 的职责区分：
#   - inspect: 查看 Plan 多步执行状态（任务级）
#   - explain-route: 解释单次路由决策（单步路由级）
#
# API Stability: Experimental

from __future__ import annotations

import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def cmd_inspect(args: list[str]) -> None:
    """查看 Plan 详情。

    用法：
      ai-hub inspect <plan_id>           人类可读（默认）
      ai-hub inspect <plan_id> --json    JSON 输出
      ai-hub inspect --list              列出最近 N 个 plan
      ai-hub inspect --list --json       JSON 列表
    """
    if not args:
        print('Usage: ai-hub inspect <plan_id> [--json]')
        print('       ai-hub inspect --list [--json]')
        sys.exit(1)

    json_output = "--json" in args
    non_flag_args = [a for a in args if a != "--json"]

    if non_flag_args == ["--list"]:
        _list_recent(json_output=json_output)
        return

    if not non_flag_args:
        print('Usage: ai-hub inspect <plan_id> [--json]')
        print('       ai-hub inspect --list [--json]')
        sys.exit(1)

    plan_id = non_flag_args[0]

    # 从 cli/plan.py 共享 PlanStore（进程内单例）
    from cli.plan import get_plan_store
    store = get_plan_store()
    plan = store.get(plan_id)

    if plan is None:
        print(f"Error: plan '{plan_id}' not found in current process PlanStore", file=sys.stderr)
        print(f"Hint: try `ai-hub inspect --list` to see available plans", file=sys.stderr)
        sys.exit(1)

    if json_output:
        _print_plan_json(plan)
    else:
        _print_plan_human(plan)


def _list_recent(json_output: bool) -> None:
    """列出最近 N 个 plan。"""
    from cli.plan import get_plan_store
    store = get_plan_store()
    plans = store.list_recent(limit=10)

    if json_output:
        payload = {
            "version": "0.9.3",
            "count": len(plans),
            "plans": [
                {
                    "plan_id": p.plan_id,
                    "task_id": p.task_id,
                    "status": p.status,
                    "created_at": p.created_at,
                    "step_count": p.step_count,
                }
                for p in plans
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    # 人类可读
    print("AI Hub Inspect — v0.9.3 (Current Process Only)")
    print()
    print(f"Recent Plans: {len(plans)}/{store.max_size}")
    print()
    for p in plans:
        status_icon = {"success": "✓", "failed": "✗", "partial": "⚠"}.get(p.status, "?")
        print(f"  {status_icon} {p.plan_id}  status={p.status.upper()}  steps={p.step_count}  created={p.created_at}")
    print()
    if not plans:
        print("  (no plans in current process — run `ai-hub plan` first)")


def _print_plan_human(plan) -> None:
    """人类可读 Plan 详情。"""
    from planner.plan import Plan
    from cli.trace import get_trace_collector  # V0.9.4: check trace availability

    print("AI Hub Inspect — v0.9.4 (Current Process Only)")
    print()
    print(f"Plan: {plan.plan_id}")
    print(f"Task: {plan.task_id}")
    print(f"Status: {plan.status.upper()} ({sum(1 for s in plan.steps if s.status == 'success')}/{len(plan.steps)})")
    print(f"Created: {plan.created_at}")

    # Planner / Router / Schema Version
    runtime = plan.metadata.get("runtime", {})
    planner = runtime.get("planner", "unknown")
    router = runtime.get("router", "unknown")
    print(f"Planner: {planner}")
    print(f"Router: {router}")
    print(f"Schema Version: {plan.metadata.get('schema_version', '?')}")

    # V0.9.4 (ADR-0017 D5): Trace 关联（ChatGPT 强建议）
    trace = get_trace_collector()
    if trace.has(plan.plan_id):
        print(f"Trace: Available (run `ai-hub trace {plan.plan_id}` for timeline)")
    else:
        print(f"Trace: No Trace")
    print()

    print("Steps:")
    for step in plan.steps:
        # Step 状态图标
        step_icon = {"success": "✓", "failed": "✗", "partial": "⚠", "running": "→"}.get(step.status, "?")

        print(f"  [{step.step_id}] {step_icon} {step.status}")
        content_preview = step.content[:60] + ("..." if len(step.content) > 60 else "")
        print(f"    Content: {content_preview}")
        print(f"    Capabilities: {step.capabilities}")

        # V0.9.4: execution_metrics（如有）
        if step.execution_metrics is not None:
            m = step.execution_metrics
            print(f"    Latency: {m.latency_ms}ms")

        # Execution result（如果有）
        if step.execution_result is not None:
            r = step.execution_result
            print(f"    Provider: {r.provider}")
            if r.error:
                print(f"    Error: {r.error[:80]}")
        else:
            print(f"    Provider: (not executed)")
        print()


def _print_plan_json(plan) -> None:
    """JSON Plan 详情。"""
    payload = {
        "version": "0.9.3",
        "plan": plan.to_dict(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    cmd_inspect(sys.argv[1:])
