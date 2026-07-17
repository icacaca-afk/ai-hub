# AI Hub — CLI stats
# V0.9.7: Execution Statistics (ADR-0020)
#
# 用法：
#   ai-hub stats                          全局统计（全部 plans）
#   ai-hub stats --plan <plan_id>         某 plan 的统计
#   ai-hub stats --provider <name>        某 provider 的统计
#   ai-hub stats --since <iso> --until <iso>  时间范围
#   ai-hub stats --json                   JSON 输出
#
# 数据来源：SQLiteExecutionStore.query_events() → StatisticsCollector.compute()
# 设计要点（ADR-0020 决策 8）：
#   - stats 派生全部从 events（不调 PlanStore）
#   - StatisticsCollector 是纯 Read-Only Projection（ChatGPT 唯一补充原则）
#
# API Stability: Experimental

from __future__ import annotations

import json
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def cmd_stats(args: list[str]) -> None:
    """查看 Execution Statistics（V0.9.7）。

    用法：
      ai-hub stats                          全局统计
      ai-hub stats --plan <plan_id>         某 plan 的统计
      ai-hub stats --provider <name>        某 provider 的统计
      ai-hub stats --since <iso> --until <iso>  时间范围
      ai-hub stats --json                   JSON 输出
    """
    json_output = "--json" in args
    plan_id: str | None = None
    provider: str | None = None
    since: str | None = None
    until: str | None = None

    # 解析参数
    filtered = [a for a in args if a != "--json"]
    i = 0
    while i < len(filtered):
        a = filtered[i]
        if a == "--plan" and i + 1 < len(filtered):
            plan_id = filtered[i + 1]
            i += 2
            continue
        if a.startswith("--plan="):
            plan_id = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--provider" and i + 1 < len(filtered):
            provider = filtered[i + 1]
            i += 2
            continue
        if a.startswith("--provider="):
            provider = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--since" and i + 1 < len(filtered):
            since = filtered[i + 1]
            i += 2
            continue
        if a.startswith("--since="):
            since = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--until" and i + 1 < len(filtered):
            until = filtered[i + 1]
            i += 2
            continue
        if a.startswith("--until="):
            until = a.split("=", 1)[1]
            i += 1
            continue
        i += 1

    # 通过 query_events 拿 events（ADR-0020 决策 8：stats 派生全部从 events）
    from cli.history import get_execution_store
    from planner.statistics import StatisticsCollector

    store = get_execution_store()
    events = store.query_events(
        plan_id=plan_id,
        provider=provider,  # CLI 当前只传单 provider（ChatGPT Q7：接口已支持 list[str]）
        since=since,
        until=until,
    )

    # StatisticsCollector 是纯 Read-Only Projection（ChatGPT 唯一补充原则）
    stats = StatisticsCollector.compute(events)

    if json_output:
        _print_json(stats, store, plan_id, provider, since, until)
    else:
        _print_human(stats, store, plan_id, provider, since, until)


def _print_json(stats, store, plan_id, provider, since, until) -> None:
    """JSON 输出。"""
    payload = {
        "version": "0.9.7",
        "source": "sqlite",
        "db_path": str(store.db_path),
        "filters": {
            "plan_id": plan_id,
            "provider": provider,
            "since": since,
            "until": until,
        },
        **stats.to_dict(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_human(stats, store, plan_id, provider, since, until) -> None:
    """人类可读输出。"""
    print("AI Hub Statistics — v0.9.7 (SQLite)")
    print(f"  DB: {store.db_path}")
    print()

    # 过滤条件
    filters = []
    if plan_id is not None:
        filters.append(f"plan={plan_id}")
    if provider is not None:
        filters.append(f"provider={provider}")
    if since is not None:
        filters.append(f"since={since}")
    if until is not None:
        filters.append(f"until={until}")
    if filters:
        print(f"Filters: {', '.join(filters)}")
        print()

    # 时间范围
    if stats.since is not None and stats.until is not None:
        print(f"Time Range: {stats.since} ~ {stats.until}")
    else:
        print("Time Range: (no events)")
    print()

    # Plans
    success_rate_pct = stats.success_rate * 100
    print(f"Plans: {stats.plan_total} total")
    if stats.plan_total > 0:
        print(f"  Success: {stats.plan_success} ({success_rate_pct:.1f}%)")
        print(f"  Failed:  {stats.plan_failed} ({100 - success_rate_pct:.1f}%)")
    print()

    # Steps / Events
    print(f"Steps:  {stats.step_total} total")
    print(f"Events: {stats.event_total} total")
    print()

    # Providers
    if stats.providers:
        print("Providers:")
        for p in stats.providers:
            # ChatGPT V0.9.6 建议：cost 标注 "est."（Windows 终端兼容性）
            print(
                f"  {p.name:<20} {p.calls:>3} calls  "
                f"avg {p.avg_latency_ms:>6.0f}ms  "
                f"{p.total_token_in:>6} in  {p.total_token_out:>6} out  "
                f"est. ${p.total_cost_usd:.4f}"
            )
        print()

    # Latency
    print(f"Average Plan Latency: {stats.avg_plan_latency_ms:.0f}ms")
    print(f"Average Step Latency: {stats.avg_step_latency_ms:.0f}ms")
    print()

    # Total Cost
    print(f"Total Estimated Cost: ${stats.total_cost_usd:.4f}")
    print()


if __name__ == "__main__":
    cmd_stats(sys.argv[1:])
