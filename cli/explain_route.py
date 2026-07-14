# AI Hub — CLI explain-route
# V0.7.1: 产品化 last_route_reason
#
# 用法：
#   ai-hub explain-route "写一个Python排序算法"
#
# 输出 Task → Capability → Candidates → Decision 的完整路由解释。

from __future__ import annotations

import sys
from typing import Optional

from core.registry import CapabilityRegistry
from core.task import Task
from core.health_registry import HealthRegistry
from core.quota import QuotaManager
from router.health_router import HealthAwareRouter


def cmd_explain_route(args: list[str]) -> None:
    """解释路由决策过程。

    展示：
    1. Task 识别出的 capabilities
    2. 所有候选 Provider 的 health/quota/priority 状态
    3. 最终选择结果和原因
    """
    if not args:
        print('Usage: ai-hub explain-route "<task description>"')
        sys.exit(1)

    text = " ".join(args)
    registry = _build_registry()
    quota = QuotaManager()
    hr = HealthRegistry()
    router = HealthAwareRouter(registry, quota_manager=quota, health_registry=hr)

    task = Task.from_text(text)

    # ── 获取所有候选 Provider 的详细信息 ──
    caps = task.capabilities
    candidates = registry.find_by_any_capability(caps)
    reports = hr.get_all(candidates, lazy=False)

    # ── 执行路由 ──
    selected = router.route(task)
    reason = router.last_route_reason

    # ── 输出 ──
    print("AI Hub Route Explanation v0.7.1")
    print()
    print(f"Task:")
    print(f"  {text}")
    print()
    print(f"Capabilities:")
    for cap in caps:
        print(f"  {cap}")
    print()
    print(f"Candidates ({len(candidates)}):")
    print()

    for p in candidates:
        r = reports.get(p.name)
        is_selected = selected and selected.name == p.name

        marker = " → SELECTED" if is_selected else ""
        print(f"  {p.metadata.display_name or p.name}{marker}")
        print(f"    name:     {p.name}")

        if r:
            status_str = _format_health(r.status)
            print(f"    health:   {status_str}")
            if r.message and r.status != "healthy":
                print(f"    reason:   {r.message}")
        else:
            print(f"    health:   ? unknown")

        print(f"    priority: {p.metadata.priority}")

        # Quota
        if quota.exhausted(p.name):
            print(f"    quota:    ✗ exhausted")
        else:
            print(f"    quota:    ✓ available")

        # Bridge type
        bridge_name = type(p.bridge).__name__
        print(f"    bridge:   {bridge_name}")
        print()

    # ── Decision ──
    print("Decision:")
    if selected:
        group = reason.get("group", "?")
        print(f"  Selected:  {selected.name}")
        print(f"  Group:     {group}")
    else:
        print(f"  Selected:  (none)")
        print(f"  Reason:    {reason.get('reason', 'unknown')}")

    # Skipped
    skipped = reason.get("skipped", [])
    if skipped:
        print(f"  Skipped:")
        for s in skipped:
            print(f"    - {s}")

    print()


def _format_health(status: str) -> str:
    icons = {
        "healthy": "✓ healthy",
        "degraded": "⚡ degraded",
        "unknown": "? unknown",
        "unavailable": "✗ unavailable",
    }
    return icons.get(status, status)


def _build_registry() -> CapabilityRegistry:
    """构建 CapabilityRegistry（与 cli/main.py 一致）。"""
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

    from providers.fake_browser.provider import FakeBrowserProvider
    registry.register(FakeBrowserProvider())

    from providers.web_ai.provider import WebAIProvider
    registry.register(WebAIProvider())

    return registry
