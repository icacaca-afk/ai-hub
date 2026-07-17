# AI Hub — CLI trace
# V0.9.4: Plan 执行 Timeline 视图
#
# 用法：
#   ai-hub trace <plan_id>           Timeline（人类可读）
#   ai-hub trace <plan_id> --json    Timeline JSON
#   ai-hub trace --list              列出被 trace 的 plan_id
#
# 数据来源：进程内 InMemoryTraceCollector（环形缓冲 N=10，V0.9.4）。
# ⚠️ **Current Process Only**（ChatGPT 审核建议）：不持久化，进程退出后丢失。
# 跨进程持久化由 V0.9.5+ Execution History 引入。
#
# 与 inspect 的职责区分（V0.9.4 ADR-0017 D5）：
#   - inspect: 答「发生了什么？」 → PlanStore（业务）
#   - trace:   答「怎么发生的？」 → TraceCollector（过程）
#
# 视图本质：Timeline（ChatGPT 强建议 D6：不是 log）
#   - 真实时间戳（12:01:00.000）
#   - 相对时间（0.0s, 0.3s）
#   - 派生 Step/Plan latency（不显式记录 Event.latency，只记 Provider）
#
# API Stability: Experimental

from __future__ import annotations

import json
import sys
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# V0.9.4: 进程内 InMemoryTraceCollector 单例（与 cli/plan.py 的 _PLAN_STORE 共享）
# V0.9.4 设计：cli/plan.py 注入 event_bus + collector，cli/trace.py 读取
class _TraceHolder:
    """单例 holder（避免 module-level global 绑定问题）。"""
    collector = None  # type: ignore


def set_trace_collector(collector) -> None:
    """注入 TraceCollector 单例（V0.9.4 cli/plan.py 启动时调用）。"""
    _TraceHolder.collector = collector


def get_trace_collector():
    """获取 TraceCollector 单例（cli/inspect.py 等使用）。"""
    if _TraceHolder.collector is None:
        # 默认 lazy init（无 EventBus，仅返回空 collector）
        from planner.trace_collector import InMemoryTraceCollector
        _TraceHolder.collector = InMemoryTraceCollector()
    return _TraceHolder.collector


def cmd_trace(args: list[str]) -> None:
    """查看 Plan 执行 Timeline。

    用法：
      ai-hub trace <plan_id>           Timeline（默认）
      ai-hub trace <plan_id> --json    Timeline JSON
      ai-hub trace --list              列出被 trace 的 plan_id
    """
    if not args:
        print('Usage: ai-hub trace <plan_id> [--json]')
        print('       ai-hub trace --list')
        sys.exit(1)

    json_output = "--json" in args
    non_flag_args = [a for a in args if a != "--json"]

    if non_flag_args == ["--list"]:
        _list_traced_plans(json_output=json_output)
        return

    if not non_flag_args:
        print('Usage: ai-hub trace <plan_id> [--json]')
        print('       ai-hub trace --list')
        sys.exit(1)

    plan_id = non_flag_args[0]
    collector = get_trace_collector()

    if not collector.has(plan_id):
        print(f"Error: trace for plan '{plan_id}' not found in current process", file=sys.stderr)
        print(f"Hint: try `ai-hub trace --list` to see available traces", file=sys.stderr)
        print(f"      (the plan must have been executed in this process)", file=sys.stderr)
        sys.exit(1)

    events = collector.get_trace(plan_id)
    if json_output:
        _print_trace_json(plan_id, events)
    else:
        _print_trace_human(plan_id, events)


def _list_traced_plans(json_output: bool) -> None:
    """列出被 trace 的 plan_id。"""
    collector = get_trace_collector()
    plans = collector.list_traced_plans()

    if json_output:
        payload = {
            "version": "0.9.4",
            "count": len(plans),
            "traced_plans": plans,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    # 人类可读
    print("AI Hub Trace — v0.9.4 (Current Process Only)")
    print()
    print(f"Traced Plans: {len(plans)}/{collector.max_size}")
    print()
    if not plans:
        print("  (no traces in current process — run `ai-hub plan` first)")
        return
    for plan_id in plans:
        event_count = len(collector.get_trace(plan_id))
        print(f"  • {plan_id}  events={event_count}")


def _print_trace_human(plan_id: str, events: list) -> None:
    """人类可读 Timeline 视图。"""
    print("AI Hub Trace — v0.9.4 (Current Process Only)")
    print()
    print(f"Plan: {plan_id}")
    print(f"Events: {len(events)}")
    print()

    if not events:
        print("  (no events)")
        return

    # 计算相对时间（基于第一个 event 的 timestamp）
    t0 = _parse_iso(events[0].timestamp)
    plan_start_t = t0

    # 找 plan_finished 时间
    plan_finished = next((e for e in events if e.type == "plan_finished"), None)
    total_latency = ""
    if plan_finished is not None:
        t1 = _parse_iso(plan_finished.timestamp)
        delta = (t1 - t0).total_seconds()
        total_latency = f", {delta:.3f}s total"

    print(f"Timeline{(' — ' + _format_t(plan_start_t) + total_latency) if events else ''}:")
    print()

    for event in events:
        t = _parse_iso(event.timestamp)
        rel = (t - t0).total_seconds()

        # 渲染 event
        desc = _describe_event(event)
        print(f"  {_format_t(t)}  {rel:5.3f}s  {desc}")
    print()


def _describe_event(event) -> str:
    """渲染 event 为简短描述。"""
    type_ = event.type
    data = event.data or {}

    if type_ == "plan_started":
        return f"plan_started  task_id={data.get('task_id', '?')[:16]}"
    elif type_ == "planner_started":
        return f"planner_started  ({data.get('planner', '?')})"
    elif type_ == "planner_finished":
        return f"planner_finished  ({data.get('step_count', '?')} steps)"
    elif type_ == "step_started":
        idx = data.get("index", "?")
        preview = data.get("content_preview", "")
        return f"step_started  [step-{idx}: {preview}]"
    elif type_ == "provider_selected":
        return f"provider_selected  ({event.provider or '?'})"
    elif type_ == "provider_finished":
        lat = event.latency_ms if event.latency_ms is not None else "?"
        return f"provider_finished  ({event.provider}, {lat}ms, {data.get('status', '?')})"
    elif type_ == "step_finished":
        idx = (event.step_id or "").replace("step-", "")
        lat = data.get("latency_ms", "?")
        return f"step_finished  [step-{idx}: {data.get('status', '?')}, {lat}ms]"
    elif type_ == "plan_finished":
        return f"plan_finished  ({data.get('status', '?')}, {data.get('success', '?')}/{data.get('steps', '?')})"
    else:
        return f"{type_}  (data={data})"


def _print_trace_json(plan_id: str, events: list) -> None:
    """JSON Timeline 视图。"""
    payload = {
        "version": "0.9.4",
        "plan_id": plan_id,
        "event_count": len(events),
        "events": [e.to_dict() for e in events],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_iso(ts: str) -> datetime:
    """解析 ISO 8601 时间戳。"""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _format_t(t: datetime) -> str:
    """格式化为 HH:MM:SS.mmm。"""
    return t.strftime("%H:%M:%S.") + f"{t.microsecond // 1000:03d}"


if __name__ == "__main__":
    cmd_trace(sys.argv[1:])
