# AI Hub — Web AI Provider
#
# 通用 Web AI Provider，通过 BrowserBridge 操控浏览器与 Web AI 服务交互。
#
# 这是 V0.5 Alpha 的第一个真实 Web AI Provider。
# 不需要改 core/，完全通过 providers/ 扩展。
#
# 使用方式：
#   1. 安装 Playwright + chromium
#   2. 配置目标 AI 网站的 selectors（通过环境变量或代码修改）
#   3. 通过 CLI: python -m cli.main ask "搜索 AI Hub" --capability browser.navigate
#
# API Stability: Experimental (V0.5 Alpha)

from __future__ import annotations

import os
import tempfile

from core.provider import Provider, ProviderMetadata
from core.bridge import BrowserBridge


class WebAIProvider(Provider):
    """Web AI Provider，通过 BrowserBridge 与 Web AI 服务交互。

    第一个真实用例：通过浏览器打开 AI 网站，输入问题，等待回答，提取结果。

    环境变量：
        AI_HUB_WEB_AI_URL       — 目标 AI 网站 URL
        AI_HUB_WEB_AI_INPUT     — 输入框 selector
        AI_HUB_WEB_AI_SUBMIT    — 提交按钮 selector
        AI_HUB_WEB_AI_OUTPUT    — 回答区域 selector
        AI_HUB_SCREENSHOT_DIR   — 截图目录
    """

    # 从环境变量读取配置，有默认值
    _target_url = os.environ.get("AI_HUB_WEB_AI_URL", "")
    _input_selector = os.environ.get("AI_HUB_WEB_AI_INPUT", "")
    _submit_selector = os.environ.get("AI_HUB_WEB_AI_SUBMIT", "")
    _output_selector = os.environ.get("AI_HUB_WEB_AI_OUTPUT", "")
    _screenshot_dir = os.environ.get(
        "AI_HUB_SCREENSHOT_DIR",
        os.path.join(tempfile.gettempdir(), "ai_hub_browser"),
    )

    metadata = ProviderMetadata(
        name="web_ai",
        display_name="Web AI",
        description="Web AI service via browser automation (Playwright)",
        version="0.1.0",
        capabilities=[
            "browser.navigate",
            "browser.scrape",
            "browser.screenshot",
            "browser.interact",
            "general.chat",
        ],
        priority=20,
        fallback=["demo"],
        quota_type="unlimited",
        quota_total=-1,
        timeout=120,
    )

    bridge = BrowserBridge(
        headless=True,
        browser_type="chromium",
        timeout=120,
        screenshot_dir=_screenshot_dir,
    )

    def health(self) -> bool:
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        # Web AI 不需要独立认证（浏览器登录态由用户管理）
        return self.bridge.check_available()

    def quota_left(self) -> int:
        return -1 if self.bridge.check_available() else 0

    def select_bridge(self, task):
        """根据 task 内容构造 actions，然后返回 bridge。

        如果 task.content 是 URL，走自动导航。
        如果配置了目标 AI 网站，构造完整的对话 actions。
        否则返回默认 bridge（由 BrowserBridge._get_actions 处理）。
        """
        content = task.content.strip()

        # 如果配置了目标 AI 网站且有文本输入，构造对话 actions
        if self._target_url and self._input_selector and not content.startswith("http"):
            task.context = task.context or {}
            if "actions" not in task.context:
                task.context["actions"] = [
                    {"action": "goto", "url": self._target_url},
                    {"action": "wait", "selector": self._input_selector, "timeout": 15000},
                    {"action": "input", "selector": self._input_selector, "text": content},
                ]
                if self._submit_selector:
                    task.context["actions"].append(
                        {"action": "click", "selector": self._submit_selector}
                    )
                if self._output_selector:
                    task.context["actions"].extend([
                        {"action": "wait", "selector": self._output_selector, "timeout": 60000},
                        {"action": "extract", "selector": self._output_selector},
                    ])
                task.context["actions"].append(
                    {"action": "screenshot", "name": "web_ai_result"}
                )

        return self.bridge
