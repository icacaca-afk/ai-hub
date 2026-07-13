# AI Hub — BrowserBridge Contract Tests
#
# 验证 BrowserBridge 的接口契约：
# 1. check_available() 在 Playwright 安装后返回 True
# 2. URL 自动导航 + 截图
# 3. 结构化 actions 执行
# 4. extract 提取页面内容
# 5. evaluate 执行 JS
# 6. 错误处理（无效 URL / 未知 action）
# 7. Provider 契约（FakeBrowserProvider 使用 BrowserBridge）
#
# 注意：这些测试需要 Playwright + chromium 已安装。
# 未安装时自动 skip。

from __future__ import annotations

import os
import sys
import tempfile

import pytest

# 确保项目根目录在 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.bridge import BrowserBridge, BridgeResult
from core.task import Task


# --- Playwright availability check (module-level for skipif) ---

def _check_playwright():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


# Skip entire module if Playwright not available
pytestmark = pytest.mark.skipif(
    not _check_playwright(),
    reason="Playwright + chromium not installed"
)


# --- Fixtures ---

@pytest.fixture
def screenshot_dir():
    d = tempfile.mkdtemp(prefix="ai_hub_test_")
    return d


@pytest.fixture
def bridge(screenshot_dir):
    return BrowserBridge(
        headless=True,
        browser_type="chromium",
        timeout=15,
        screenshot_dir=screenshot_dir,
    )


# --- Tests ---

class TestBrowserBridgeAvailability:
    """BrowserBridge 可用性检查。"""

    def test_check_available_true(self, bridge):
        """Playwright 安装后 check_available() 应返回 True。"""
        assert bridge.check_available() is True

    def test_check_auth_equals_available(self, bridge):
        """check_auth() 应与 check_available() 一致。"""
        assert bridge.check_auth() == bridge.check_available()


class TestBrowserBridgeURLAutoNav:
    """URL 自动导航 + 截图。"""

    def test_url_auto_navigate_and_screenshot(self, bridge):
        """task.content 是 URL 时，自动构造 goto + screenshot。"""
        task = Task(
            content="https://example.com",
            capabilities=["browser.navigate"],
        )
        result = bridge.run(task)

        assert result.success is True
        assert "Navigated to: https://example.com" in result.output
        assert "Screenshot:" in result.output
        assert len(result.artifacts) == 1
        assert os.path.exists(result.artifacts[0])


class TestBrowserBridgeStructuredActions:
    """结构化 actions 执行。"""

    def test_goto_wait_extract(self, bridge):
        """goto + wait + extract 链路。"""
        task = Task(
            content="structured actions",
            capabilities=["browser.navigate", "browser.scrape"],
            context={
                "actions": [
                    {"action": "goto", "url": "https://example.com"},
                    {"action": "wait", "selector": "h1", "timeout": 10000},
                    {"action": "extract", "selector": "h1"},
                ]
            },
        )
        result = bridge.run(task)

        assert result.success is True
        assert "Navigated to:" in result.output
        assert "Extracted" in result.output
        assert "Example Domain" in result.output

    def test_screenshot_with_name(self, bridge, screenshot_dir):
        """screenshot action 生成文件到 screenshot_dir。"""
        task = Task(
            content="screenshot test",
            capabilities=["browser.screenshot"],
            context={
                "actions": [
                    {"action": "goto", "url": "https://example.com"},
                    {"action": "screenshot", "name": "example_page"},
                ]
            },
        )
        result = bridge.run(task)

        assert result.success is True
        assert len(result.artifacts) == 1
        assert "example_page.png" in result.artifacts[0]
        assert os.path.exists(result.artifacts[0])

    def test_evaluate_javascript(self, bridge):
        """evaluate action 执行 JS 并返回结果。"""
        task = Task(
            content="js eval test",
            capabilities=["browser.interact"],
            context={
                "actions": [
                    {"action": "goto", "url": "https://example.com"},
                    {"action": "evaluate", "script": "document.title"},
                ]
            },
        )
        result = bridge.run(task)

        assert result.success is True
        assert "Example Domain" in result.output

    def test_scroll_action(self, bridge):
        """scroll action 不报错。"""
        task = Task(
            content="scroll test",
            capabilities=["browser.interact"],
            context={
                "actions": [
                    {"action": "goto", "url": "https://example.com"},
                    {"action": "scroll", "dy": 100},
                ]
            },
        )
        result = bridge.run(task)

        assert result.success is True
        assert "Scrolled down 100px" in result.output

    def test_click_and_input(self, bridge):
        """click + input 动作（使用带表单的页面）。"""
        # 使用 data: URL 构造一个简单表单
        html = '<html><body><input id="q" type="text"><button id="btn">OK</button></body></html>'
        task = Task(
            content="form interaction",
            capabilities=["browser.interact"],
            context={
                "actions": [
                    {"action": "goto", "url": f"data:text/html,{html}"},
                    {"action": "input", "selector": "#q", "text": "hello ai-hub"},
                    {"action": "click", "selector": "#btn"},
                    {"action": "evaluate", "script": "document.getElementById('q').value"},
                ]
            },
        )
        result = bridge.run(task)

        assert result.success is True
        assert "Input into #q" in result.output
        assert "Clicked: #btn" in result.output
        assert "hello ai-hub" in result.output


class TestBrowserBridgeErrorHandling:
    """错误处理。"""

    def test_no_actions_returns_error(self, bridge):
        """没有 actions 时返回错误。"""
        task = Task(
            content="just some text, no actions",
            capabilities=["browser.navigate"],
        )
        result = bridge.run(task)

        assert result.success is False
        assert "No actions" in result.error

    def test_unknown_action_logged_not_fatal(self, bridge):
        """未知 action 不应中断整个流程。"""
        task = Task(
            content="unknown action test",
            capabilities=["browser.navigate"],
            context={
                "actions": [
                    {"action": "goto", "url": "https://example.com"},
                    {"action": "frobnicate", "target": "something"},
                    {"action": "screenshot", "name": "after_unknown"},
                ]
            },
        )
        result = bridge.run(task)

        # 整体应成功（未知 action 只是被记录）
        assert result.success is True
        assert "Unknown action: frobnicate" in result.output
        assert len(result.artifacts) == 1

    def test_invalid_url_returns_error(self, bridge):
        """无效 URL 应返回错误。"""
        task = Task(
            content="bad url",
            capabilities=["browser.navigate"],
            context={
                "actions": [
                    {"action": "goto", "url": "https://this-domain-does-not-exist-12345.com"},
                ]
            },
        )
        result = bridge.run(task)

        assert result.success is False
        assert "BrowserBridge error" in result.error


class TestBrowserBridgeProviderIntegration:
    """FakeBrowserProvider + BrowserBridge 集成。"""

    def test_fake_browser_provider_contract(self):
        """FakeBrowserProvider 接口契约。"""
        from providers.fake_browser.provider import FakeBrowserProvider

        p = FakeBrowserProvider()
        assert p.metadata.name == "fake_browser"
        assert "browser.navigate" in p.metadata.capabilities
        assert "browser.screenshot" in p.metadata.capabilities
        assert p.metadata.priority == 10
        assert p.metadata.fallback == ["demo"]

    def test_fake_browser_provider_available(self):
        """FakeBrowserProvider 在 Playwright 安装后应可用。"""
        from providers.fake_browser.provider import FakeBrowserProvider

        p = FakeBrowserProvider()
        assert p.available() is True
        assert p.health() is True

    def test_fake_browser_provider_select_bridge(self):
        """select_bridge 返回 BrowserBridge 实例。"""
        from providers.fake_browser.provider import FakeBrowserProvider
        from core.bridge import BrowserBridge

        p = FakeBrowserProvider()
        task = Task(content="test", capabilities=["browser.navigate"])
        bridge = p.select_bridge(task)

        assert isinstance(bridge, BrowserBridge)

    def test_end_to_end_via_provider(self):
        """通过 Provider → Bridge 完整链路。"""
        from providers.fake_browser.provider import FakeBrowserProvider

        p = FakeBrowserProvider()
        task = Task(
            content="https://example.com",
            capabilities=["browser.navigate"],
        )
        bridge = p.select_bridge(task)
        result = bridge.run(task)

        assert result.success is True
        assert len(result.artifacts) == 1
