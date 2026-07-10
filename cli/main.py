# AI Hub — CLI 入口
#
# 用法：
#   ai-hub ask "写一个 Python HTTP 服务"
#   ai-hub history
#   ai-hub status

from __future__ import annotations

import sys
import time
from typing import Any

# Windows 控制台编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.provider import Provider
from core.registry import ProviderRegistry
from core.result import Result
from core.history import HistoryStore
from router.router import Router, classify_task


def _build_registry() -> ProviderRegistry:
    """构建 Provider 注册中心。

    第一版硬编码注册。V0.2 会改为从配置文件自动发现。
    """
    registry = ProviderRegistry()

    # 注册 Demo Provider（骨架验证用）
    from providers.demo.provider import DemoProvider
    registry.register(DemoProvider())

    # TODO: 接入真实 Provider 后取消注释
    # from providers.qoder.provider import QoderProvider
    # registry.register(QoderProvider())
    # from providers.gemini.provider import GeminiProvider
    # registry.register(GeminiProvider())
    # from providers.qclaw.provider import QClawProvider
    # registry.register(QClawProvider())

    return registry


def cmd_ask(args: list[str]) -> None:
    """执行一个任务。"""
    if not args:
        print("Usage: ai-hub ask \"<task description>\"")
        sys.exit(1)

    task = " ".join(args)
    registry = _build_registry()
    router = Router(registry)
    history = HistoryStore()

    # 路由
    task_type, provider = router.route(task)

    if provider is None:
        print(f"[Router] No available provider for task type '{task_type}'")
        print(f"[Router] Task: {task}")
        sys.exit(1)

    print(f"[Router] Task type: {task_type}")
    print(f"[Router] Provider:  {provider.display_name}")
    print()

    # 执行
    start = time.time()
    result = provider.execute(task)
    duration = int((time.time() - start) * 1000)

    # 补充 metadata
    if "duration_ms" not in result.metadata:
        result.metadata["duration_ms"] = duration

    # 记录历史
    history.add(task, task_type, provider.name, result)

    # 输出结果
    print(result.output)

    if not result.is_success:
        print(f"\n[Error] {result.error}", file=sys.stderr)
        sys.exit(1)


def cmd_history(args: list[str]) -> None:
    """查看历史记录。"""
    history = HistoryStore()
    limit = 10

    # 解析参数
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
    """查看所有 Provider 状态。"""
    registry = _build_registry()
    providers = registry.all()

    print("AI Hub — Provider Status\n")
    print(f"{'Name':<15} {'Display':<12} {'Available':<10} {'Quota':<10} {'Priority':<8}")
    print("-" * 55)

    for p in providers:
        avail = "✅" if p.available() else "❌"
        quota = p.quota_left()
        quota_str = "∞" if quota == -1 else str(quota)
        print(f"{p.name:<15} {p.display_name:<12} {avail:<10} {quota_str:<10} {p.priority:<8}")


def cmd_quota(args: list[str]) -> None:
    """查看额度。"""
    registry = _build_registry()
    providers = registry.all()

    print("AI Hub — Quota Status\n")
    for p in providers:
        info = p.quota_info()
        remaining = info["remaining"]
        total = info["total"]
        if remaining == -1:
            print(f"  {p.display_name:<12} Unlimited")
        else:
            print(f"  {p.display_name:<12} {remaining}/{total} remaining ({info['type']})")


def main() -> None:
    """CLI 主入口。"""
    if len(sys.argv) < 2:
        print("AI Hub — One command. Multiple providers. Free-first routing.\n")
        print("Usage:")
        print("  ai-hub ask \"<task>\"    Execute a task")
        print("  ai-hub history [N]      Show recent N tasks (default 10)")
        print("  ai-hub status           Show provider status")
        print("  ai-hub quota            Show quota status")
        sys.exit(0)

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "ask": cmd_ask,
        "history": cmd_history,
        "status": cmd_status,
        "quota": cmd_quota,
    }

    if command not in commands:
        print(f"Unknown command: {command}")
        print(f"Available commands: {', '.join(commands.keys())}")
        sys.exit(1)

    commands[command](args)


if __name__ == "__main__":
    main()
