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

    return registry


def cmd_ask(args: list[str]) -> None:
    if not args:
        print('Usage: ai-hub ask "<task description>"')
        sys.exit(1)

    text = " ".join(args)
    registry = _build_registry()
    router = Router(registry)
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
    registry = _build_registry()
    providers = registry.all()

    print("AI Hub — Quota Status\n")
    for p in providers:
        info = p.quota_info()
        remaining = info["remaining"]
        total = info["total"]
        if remaining == -1:
            print(f"  {p.display_name:<14} Unlimited ({type(p.bridge).__name__})")
        else:
            print(f"  {p.display_name:<14} {remaining}/{total} remaining ({info['type']})")


def cmd_caps(args: list[str]) -> None:
    """列出所有能力标签和对应的 Provider。"""
    registry = _build_registry()
    from core.capabilities import CAPABILITIES

    print("AI Hub — Capabilities\n")
    for cap, desc in sorted(CAPABILITIES.items()):
        providers = registry.find_by_capability(cap)
        provider_names = ", ".join(p.name for p in providers) or "(none)"
        print(f"  {cap:<20} {desc:<12} -> {provider_names}")


def main() -> None:
    if len(sys.argv) < 2:
        print("AI Hub — One Task. Any AI. Any Runtime.\n")
        print("Usage:")
        print('  ai-hub ask "<task>"    Execute a task')
        print("  ai-hub history [N]      Show recent N tasks (default 10)")
        print("  ai-hub status           Show provider status")
        print("  ai-hub quota            Show quota status")
        print("  ai-hub caps             Show capability mapping")
        sys.exit(0)

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "ask": cmd_ask,
        "history": cmd_history,
        "status": cmd_status,
        "quota": cmd_quota,
        "caps": cmd_caps,
    }

    if command not in commands:
        print(f"Unknown command: {command}")
        print(f"Available commands: {', '.join(commands.keys())}")
        sys.exit(1)

    commands[command](args)


if __name__ == "__main__":
    main()
