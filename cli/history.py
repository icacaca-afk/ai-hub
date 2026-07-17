# AI Hub — CLI exec-history
# V0.9.5: Plan Execution History (SQLite 持久化，跨进程)
#
# 用法：
#   ai-hub exec-history                       列出最近 N 个 plan execution（默认 20）
#   ai-hub exec-history --plan <plan_id>      查某 plan 的 timeline
#   ai-hub exec-history --json                JSON 输出
#   ai-hub exec-history --limit N             限制条数
#   ai-hub exec-history --plan <id> --json    timeline JSON
#
# 数据来源：SQLiteExecutionStore（持久化，跨进程，ADR-0018）。
# 与 trace 的职责区分：
#   - trace:   答「当前进程怎么发生的？」 → InMemoryTraceCollector（进程内，退出丢失）
#   - history: 答「历史发生过什么？」     → SQLiteExecutionStore（持久化，跨进程）
#
# 命令名用 ``exec-history``（``history`` 已被 cli/main.py 的 cmd_history 占用）。
#
# API Stability: Experimental

from __future__ import annotations

import json
import sys
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# V0.9.5: SQLiteExecutionStore 单例 holder（同 cli/trace.py 的 _TraceHolder 模式）
# 设计：cli/plan.py 启动时构造 store + attach + 注入此处，cli/history.py 读取
class _HistoryHolder:
    """单例 holder（避免 module-level global 绑定问题）。"""
    store = None  # type: ignore


def set_execution_store(store) -> None:
    """注入 SQLiteExecutionStore 单例（V0.9.5 cli/plan.py 启动时调用）。"""
    _HistoryHolder.store = store


def get_execution_store():
    """获取 SQLiteExecutionStore 单例（lazy init）。"""
    if _HistoryHolder.store is None:
        from planner.sqlite_execution_store import SQLiteExecutionStore
        _HistoryHolder.store = SQLiteExecutionStore()
    return _HistoryHolder.store


def cmd_exec_history(args: list[str]) -> None:
    """查看 Plan Execution History（V0.9.5 SQLite 持久化）。

    用法：
      ai-hub exec-history                       列出最近 N 个 plan execution
      ai-hub exec-history --plan <plan_id>      查某 plan 的 timeline
      ai-hub exec-history --json                JSON 输出
      ai-hub exec-history --limit N             限制条数
    """
    json_output = "--json" in args
    limit = 20
    plan_id = None

    # 解析非 --json 参数
    filtered = [a for a in args if a != "--json"]
    i = 0
    while i < len(filtered):
        a = filtered[i]
        if a == "--limit" and i + 1 < len(filtered):
            try:
                limit = int(filtered[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        if a == "--plan" and i + 1 < len(filtered):
            plan_id = filtered[i + 1]
            i += 2
            continue
        if a.startswith("--plan="):
            plan_id = a.split("=", 1)[1]
            i += 1
            continue
        i += 1

    if plan_id is not None:
        _show_timeline(plan_id, json_output=json_output)
    else:
        _list_executions(json_output=json_output, limit=limit)


def _list_executions(json_output: bool, limit: int) -> None:
    """列出最近 N 个 plan execution。"""
    store = get_execution_store()
    executions = store.list_plans(limit=limit)

    if json_output:
        payload = {
            "version": "0.9.5",
            "source": "sqlite",
            "db_path": str(store.db_path),
            "count": len(executions),
            "executions": executions,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    # 人类可读
    print("AI Hub Execution History — v0.9.5 (SQLite)")
    print()
    print(f"Recent Executions: {len(executions)}")
    print()
    if not executions:
        print("  (no executions — run `ai-hub plan` first)")
        return
    for ex in executions:
        status = str(ex.get("status", "unknown")).upper()
        status_icon = {"SUCCESS": "✓", "FAILED": "✗", "PARTIAL": "⚠"}.get(status, "?")
        print(
            f"  {status_icon} {ex['plan_id']}  "
            f"status={status}  events={ex['event_count']}  "
            f"steps={ex['step_count']}  started={ex['started']}"
        )
    print()


def _show_timeline(plan_id: str, json_output: bool) -> None:
    """查看某 plan 的 execution timeline。"""
    store = get_execution_store()

    if not store.has(plan_id):
        print(f"Error: execution history for plan '{plan_id}' not found", file=sys.stderr)
        print(f"Hint: try `ai-hub exec-history` to see available executions", file=sys.stderr)
        sys.exit(1)

    events = store.get_events(plan_id)

    if json_output:
        payload = {
            "version": "0.9.5",
            "source": "sqlite",
            "db_path": str(store.db_path),
            "plan_id": plan_id,
            "event_count": len(events),
            "events": [e.to_dict() for e in events],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    _print_timeline_human(plan_id, events)


def _print_timeline_human(plan_id: str, events: list) -> None:
    """人类可读 Timeline 视图（参考 cli/trace.py 格式）。"""
    print("AI Hub Execution History — v0.9.5 (SQLite)")
    print()
    print(f"Plan: {plan_id}")
    print(f"Events: {len(events)}")
    print()

    if not events:
        print("  (no events)")
        return

    # 计算相对时间（基于第一个 event 的 timestamp）
    t0 = _parse_iso(events[0].timestamp)

    # 找 plan_finished 时间
    plan_finished = next((e for e in events if e.type == "plan_finished"), None)
    total_latency = ""
    if plan_finished is not None:
        t1 = _parse_iso(plan_finished.timestamp)
        delta = (t1 - t0).total_seconds()
        total_latency = f", {delta:.3f}s total"

    print(f"Timeline — {_format_t(t0)}{total_latency}:")
    print()

    for event in events:
        t = _parse_iso(event.timestamp)
        rel = (t - t0).total_seconds()
        desc = _describe_event(event)
        print(f"  {_format_t(t)}  {rel:5.3f}s  {desc}")
    print()


def _describe_event(event) -> str:
    """渲染 event 为简短描述（与 cli/trace.py 一致的视图）。"""
    type_ = event.type
    data = event.data or {}

    if type_ == "plan_started":
        return f"plan_started  task_id={str(data.get('task_id', '?'))[:16]}"
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


def _parse_iso(ts: str) -> datetime:
    """解析 ISO 8601 时间戳。"""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _format_t(t: datetime) -> str:
    """格式化为 HH:MM:SS.mmm。"""
    return t.strftime("%H:%M:%S.") + f"{t.microsecond // 1000:03d}"


if __name__ == "__main__":
    cmd_exec_history(sys.argv[1:])
