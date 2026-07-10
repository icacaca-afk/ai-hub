# AI Hub — Fake Browser Provider（使用 BrowserBridge）
#
# 用于验证 BrowserBridge 架构，不依赖外部 Playwright 安装。
# 当 Playwright 未安装时，available() 返回 False，不影响系统运行。
# 安装 Playwright 后可直接用于浏览器自动化。

from __future__ import annotations

from core.provider import Provider, ProviderMetadata
from core.bridge import BrowserBridge


class FakeBrowserProvider(Provider):
    """Fake Browser Provider，使用 BrowserBridge。

    声明浏览器相关能力，通过 BrowserBridge 执行。
    当 Playwright 未安装时不可用，安装后自动可用。

    环境变量：
        无（Playwright 需独立安装）
    """

    metadata = ProviderMetadata(
        name="fake_browser",
        display_name="Fake Browser",
        description="Browser automation via Playwright (requires playwright install)",
        version="0.1.0",
        capabilities=[
            "browser.navigate",
            "browser.scrape",
            "browser.screenshot",
            "browser.interact",
            "general.chat",
        ],
        priority=10,
        fallback=["demo"],
        quota_type="unlimited",
        quota_total=-1,
        timeout=120,
    )

    bridge = BrowserBridge(
        headless=True,
        browser_type="chromium",
        timeout=120,
    )

    def health(self) -> bool:
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        return self.bridge.check_available()

    def quota_left(self) -> int:
        return -1 if self.bridge.check_available() else 0
