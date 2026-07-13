# AI Hub — CLI 入口
#
# 用法：
#   ai-hub ask "写一个 Python HTTP 服务"
#   ai-hub history
#   ai-hub status
#   ai-hub quota
#   ai-hub caps

from __future__ import annotations

import sys
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.registry import CapabilityRegistry
from core.task import Task
from core.history import HistoryStore
from router.router import Router


def _build_registry() -> CapabilityRegistry:
    """构建 CapabilityRegistry。

    V0.1.1: 全量注册 5 个 Provider，验证 Zero-Modification KPI。
    - demo       (FakeBridge)  — 基线
    - gemini_cli (CLIBridge)   — V0.1 真实接入
    - stub       (CLIBridge)   — V0.1.1 架构验证（同类型第二个）
    - openai_api (APIBridge)   — V0.1 真实接入
    - qoder      (CLIBridge)   — 注册但 CLI 不可用时自动降级
    """
    registry = CapabilityRegistry()

    from providers.demo.provider import DemoProvider
    registry.register(DemoProvider())

    from providers.gemini.provider import GeminiCLIProvider
    registry.register(GeminiCLIProvider())

    from providers.stub.provider import StubProvider
    registry.register(StubProvider())

    from providers.openai_api.provider import OpenAIAPIProvider
    registry.register(OpenAIAPIProvider())

    from providers.qoder.provider import QoderProvider
    registry.register(QoderProvider())

    from providers.claude_cli.provider import ClaudeCLIProvider
    registry.register(ClaudeCLIProvider())

    from providers.fake_browser.provider import FakeBrowserProvider
    registry.register(FakeBrowserProvider())

    from providers.marvis.provider import MarvisProvider
    registry.register(MarvisProvider())

    return registry


def cmd_ask(args: list[str]) -> None:
    if not args:
        print('Usage: ai-hub ask "<task description>"')
        sys.exit(1)

    text = " ".join(args)
    registry = _build_registry()
    from core.quota import QuotaManager
    quota = QuotaManager()
    router = Router(registry, quota_manager=quota)
    history = HistoryStore()

    # 创建 Task
    task = Task.from_text(text)

    print(f"[Router] Capabilities: {task.capabilities}")

    # 路由
    provider = router.route(task)

    if provider is None:
        print(f"[Router] No available provider for capabilities: {task.capabilities}")
        print(f"[Router] Task: {text}")
        sys.exit(1)

    print(f"[Router] Provider:     {provider.display_name}")
    bridge = provider.select_bridge(task)
    print(f"[Router] Bridge:       {type(bridge).__name__}")
    print()

    # 执行
    start = time.time()
    result = router.execute(task)
    duration = int((time.time() - start) * 1000)

    if "duration_ms" not in result.metadata:
        result.metadata["duration_ms"] = duration

    # 记录历史
    history.add(task.content, ",".join(task.capabilities), provider.name, result)

    # 输出
    print(result.output)

    if result.artifacts:
        print(f"\n[Artifacts]")
        for a in result.artifacts:
            print(f"  - {a}")

    if not result.is_success:
        print(f"\n[Error] {result.error}", file=sys.stderr)
        sys.exit(1)


def cmd_history(args: list[str]) -> None:
    history = HistoryStore()
    limit = 10
    for arg in args:
        if arg.isdigit():
            limit = int(arg)

    records = history.recent(limit)
    if not records:
        print("No history yet.")
        return

    print(f"Recent {len(records)} tasks:\n")
    for i, r in enumerate(records, 1):
        status_icon = "✅" if r["status"] == "success" else "❌"
        print(f"  {i}. {status_icon} [{r['provider']}] {r['input'][:60]}")
        print(f"     {r['timestamp']} | {r['task_type']} | {r['duration_ms']}ms")


def cmd_status(args: list[str]) -> None:
    registry = _build_registry()
    providers = registry.all()

    print("AI Hub — Provider Status\n")
    print(f"{'Name':<15} {'Display':<14} {'Available':<10} {'Quota':<10} {'Priority':<8} {'Bridge'}")
    print("-" * 75)

    for p in providers:
        avail = "✅" if p.available() else "❌"
        quota = p.quota_left()
        quota_str = "∞" if quota == -1 else str(quota)
        bridge_type = type(p.bridge).__name__
        print(f"{p.name:<15} {p.display_name:<14} {avail:<10} {quota_str:<10} {p.priority:<8} {bridge_type}")


def cmd_quota(args: list[str]) -> None:
    from core.quota import QuotaManager

    if args and args[0] == "log":
        qm = QuotaManager()
        provider = args[1] if len(args) > 1 else None
        logs = qm.log(provider)
        if not logs:
            print("No quota log entries.")
            return
        print(f"{'Time':<22} {'Provider':<16} {'Amt':>3} {'Rem':>6}")
        print("-" * 51)
        for l in logs:
            ts = l["created_at"][:19].replace("T", " ")
            print(f"{ts:<22} {l['provider_name']:<16} {l['amount']:>3} {l['remaining']:>6}")
        return

    if args and args[0] == "reset":
        qm = QuotaManager()
        if len(args) > 1:
            qm.reset(args[1])
            print(f"Quota reset for: {args[1]}")
        else:
            qm.reset_all()
            print("All quotas reset.")
        return

    qm = QuotaManager()
    print(qm.summary())


def cmd_caps(args: list[str]) -> None:
    """列出所有能力标签和对应的 Provider。"""
    registry = _build_registry()
    from core.capabilities import CAPABILITIES

    print("AI Hub — Capabilities\n")
    for cap, desc in sorted(CAPABILITIES.items()):
        providers = registry.find_by_capability(cap)
        provider_names = ", ".join(p.name for p in providers) or "(none)"
        print(f"  {cap:<20} {desc:<12} -> {provider_names}")


def cmd_session(args: list[str]) -> None:
    from core.session import SessionManager

    if not args:
        print("Usage:")
        print('  ai-hub session list [provider]   List sessions')
        print('  ai-hub session create <provider>  Create a session')
        print('  ai-hub session show <id>          Show session details')
        print('  ai-hub session checkpoint <id>    Checkpoint a session')
        print('  ai-hub session resume <id>        Resume a session')
        print('  ai-hub session destroy <id>       Destroy a session')
        return

    sub = args[0]
    mgr = SessionManager()

    if sub == "list":
        provider = args[1] if len(args) > 1 else None
        sessions = mgr.list(provider)
        if not sessions:
            print("No sessions.")
            return
        print(f"{'ID':<12} {'Provider':<14} {'Status':<14} {'Updated':<20}")
        print("-" * 62)
        for s in sessions:
            sid = s.session_id[:8]
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s.updated_at))
            print(f"{sid:<12} {s.provider_name:<14} {s.status:<14} {ts:<20}")

    elif sub == "create":
        if len(args) < 2:
            print("Usage: ai-hub session create <provider>")
            sys.exit(1)
        s = mgr.create(args[1])
        print(f"Created session: {s.session_id}")
        print(f"  Provider: {s.provider_name}")
        print(f"  Status:   {s.status}")

    elif sub == "show":
        if len(args) < 2:
            print("Usage: ai-hub session show <id>")
            sys.exit(1)
        s = mgr.get(args[1])
        if not s:
            print(f"Session not found: {args[1]}")
            sys.exit(1)
        print(f"Session:    {s.session_id}")
        print(f"Provider:   {s.provider_name}")
        print(f"Status:     {s.status}")
        print(f"Created:    {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s.created_at))}")
        print(f"Updated:    {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s.updated_at))}")
        if s.context:
            print(f"Context:")
            for k, v in s.context.items():
                print(f"  {k}: {v}")

    elif sub == "checkpoint":
        if len(args) < 2:
            print("Usage: ai-hub session checkpoint <id>")
            sys.exit(1)
        try:
            s = mgr.checkpoint(args[1])
            print(f"Checkpointed: {s.session_id} ({s.status})")
        except (KeyError, ValueError) as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif sub == "resume":
        if len(args) < 2:
            print("Usage: ai-hub session resume <id>")
            sys.exit(1)
        try:
            s = mgr.resume(args[1])
            print(f"Resumed: {s.session_id} ({s.status})")
        except (KeyError, ValueError) as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif sub == "destroy":
        if len(args) < 2:
            print("Usage: ai-hub session destroy <id>")
            sys.exit(1)
        ok = mgr.destroy(args[1])
        if ok:
            print(f"Destroyed: {args[1]}")
        else:
            print(f"Session not found or already destroyed: {args[1]}")
            sys.exit(1)

    else:
        print(f"Unknown subcommand: {sub}")
        print("Available: list, create, show, checkpoint, resume, destroy")
        sys.exit(1)

    mgr.close()


def main() -> None:
    if len(sys.argv) < 2:
        print("AI Hub — One Task. Any AI. Any Runtime.\n")
        print("Usage:")
        print('  ai-hub ask "<task>"    Execute a task')
        print("  ai-hub history [N]      Show recent N tasks (default 10)")
        print("  ai-hub status           Show provider status")
        print("  ai-hub quota            Show quota status")
        print("  ai-hub caps             Show capability mapping")
        print("  ai-hub session <cmd>    Manage sessions")
        sys.exit(0)

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "ask": cmd_ask,
        "history": cmd_history,
        "status": cmd_status,
        "quota": cmd_quota,
        "caps": cmd_caps,
        "session": cmd_session,
    }

    if command not in commands:
        print(f"Unknown command: {command}")
        print(f"Available commands: {', '.join(commands.keys())}")
        sys.exit(1)

    commands[command](args)


if __name__ == "__main__":
    main()
