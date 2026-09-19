"""Canonical CLI provider registry construction.

单一事实来源：ask（cli/main.py）、plan（cli/plan.py）与 pipeline
introspection（cli/pipeline_inspect.py）共用同一份 Provider 注册表。
V1.0.13 审核发现 plan 注册表缺 claude_cli 导致 `plan --provider claude_cli`
报 Unknown provider——新增 Provider 只允许改这里，禁止各入口各自维护。
"""

from __future__ import annotations


def build_default_registry():
    """构建全量 CapabilityRegistry（与 `ai-hub ask` 的注册表完全一致）。"""
    from core.registry import CapabilityRegistry

    registry = CapabilityRegistry()

    from providers.demo.provider import DemoProvider
    registry.register(DemoProvider())

    from providers.gemini.provider import GeminiCLIProvider
    registry.register(GeminiCLIProvider())

    from providers.stub.provider import StubProvider
    registry.register(StubProvider())

    from providers.openai_api.provider import OpenAIAPIProvider
    registry.register(OpenAIAPIProvider())

    from providers.nine_router.provider import NineRouterProvider
    registry.register(NineRouterProvider())

    from providers.qoder.provider import QoderProvider
    registry.register(QoderProvider())

    from providers.claude_cli.provider import ClaudeCLIProvider
    registry.register(ClaudeCLIProvider())

    from providers.fake_browser.provider import FakeBrowserProvider
    registry.register(FakeBrowserProvider())

    from providers.web_ai.provider import WebAIProvider
    registry.register(WebAIProvider())

    return registry
