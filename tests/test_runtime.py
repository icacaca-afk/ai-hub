"""AI Hub — Runtime Tests

验证 BrowserBridge、GUIBridge、RuntimeRegistry 的接口契约。
不依赖 Playwright / pyautogui 安装（测试在依赖缺失时的降级行为）。

测试覆盖：
1. BrowserBridge 接口契约（run / check_available / action 解析）
2. GUIBridge 接口契约（run / check_available / action 解析）
3. RuntimeRegistry（注册 / 创建 Bridge / 可用性检查）
4. FakeBrowserProvider（Provider 契约 + 验证）
5. Bridge 继承关系
"""

import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.bridge import (
    Bridge,
    BridgeResult,
    BrowserBridge,
    GUIBridge,
    FakeBridge,
    CLIBridge,
    APIBridge,
)
from core.task import Task
from core.result import Result
from core.provider import Provider, ProviderMetadata
from core.registry import CapabilityRegistry
from core.runtime_registry import RuntimeRegistry, Runtime
from router.router import Router


# ─── 1. BrowserBridge 接口契约 ───

def test_browser_bridge_inherits_bridge():
    """BrowserBridge 必须继承 Bridge。"""
    assert issubclass(BrowserBridge, Bridge)
    print("✅ test_browser_bridge_inherits_bridge passed")


def test_browser_bridge_has_run_and_check_available():
    """BrowserBridge 必须实现 run() 和 check_available()。"""
    assert hasattr(BrowserBridge, "run")
    assert hasattr(BrowserBridge, "check_available")
    print("✅ test_browser_bridge_has_run_and_check_available passed")


def test_browser_bridge_no_actions_returns_failure():
    """没有 actions 时 _get_actions 返回空列表。"""
    bridge = BrowserBridge()
    task = Task.from_text("just some text")
    actions = bridge._get_actions(task)
    assert actions == []
    print("✅ test_browser_bridge_no_actions_returns_failure passed")


def test_browser_bridge_url_in_content_auto_actions():
    """task.content 是 URL 时自动生成 goto + screenshot actions。"""
    bridge = BrowserBridge()
    task = Task.from_text("https://example.com")
    actions = bridge._get_actions(task)
    assert len(actions) == 2
    assert actions[0]["action"] == "goto"
    assert actions[0]["url"] == "https://example.com"
    assert actions[1]["action"] == "screenshot"
    print("✅ test_browser_bridge_url_in_content_auto_actions passed")


def test_browser_bridge_actions_from_kwargs():
    """actions 通过 kwargs 传入。"""
    bridge = BrowserBridge()
    task = Task.from_text("test")
    custom_actions = [{"action": "goto", "url": "https://test.com"}]
    actions = bridge._get_actions(task, actions=custom_actions)
    assert actions == custom_actions
    print("✅ test_browser_bridge_actions_from_kwargs passed")


def test_browser_bridge_actions_from_context():
    """actions 通过 task.context 传入。"""
    bridge = BrowserBridge()
    task = Task.from_text("test", context={"actions": [{"action": "click", "selector": "#btn"}]})
    actions = bridge._get_actions(task)
    assert len(actions) == 1
    assert actions[0]["action"] == "click"
    print("✅ test_browser_bridge_actions_from_context passed")


def test_browser_bridge_actions_from_json():
    """actions 通过 JSON 格式的 task.content 传入。"""
    bridge = BrowserBridge()
    json_content = '[{"action": "goto", "url": "https://json.com"}, {"action": "screenshot"}]'
    task = Task.from_text(json_content)
    actions = bridge._get_actions(task)
    assert len(actions) == 2
    assert actions[0]["url"] == "https://json.com"
    print("✅ test_browser_bridge_actions_from_json passed")


def test_browser_bridge_check_available_returns_bool():
    """check_available() 返回 bool（不依赖 Playwright 安装）。"""
    bridge = BrowserBridge()
    result = bridge.check_available()
    assert isinstance(result, bool)
    print("✅ test_browser_bridge_check_available_returns_bool passed")


def test_browser_bridge_playwright_not_installed_returns_failure():
    """Playwright 未安装时 run() 返回明确的错误信息。"""
    bridge = BrowserBridge()
    task = Task.from_text("https://example.com")
    result = bridge.run(task)
    # 如果 Playwright 未安装，应返回失败
    if not bridge.check_available():
        assert result.success is False
        assert "not installed" in result.error.lower()
    print("✅ test_browser_bridge_playwright_not_installed_returns_failure passed")


# ─── 2. GUIBridge 接口契约 ───

def test_gui_bridge_inherits_bridge():
    """GUIBridge 必须继承 Bridge。"""
    assert issubclass(GUIBridge, Bridge)
    print("✅ test_gui_bridge_inherits_bridge passed")


def test_gui_bridge_has_run_and_check_available():
    """GUIBridge 必须实现 run() 和 check_available()。"""
    assert hasattr(GUIBridge, "run")
    assert hasattr(GUIBridge, "check_available")
    print("✅ test_gui_bridge_has_run_and_check_available passed")


def test_gui_bridge_no_actions_returns_failure():
    """没有 actions 时 _get_actions 返回空列表。"""
    bridge = GUIBridge()
    task = Task.from_text("just some text")
    actions = bridge._get_actions(task)
    assert actions == []
    print("✅ test_gui_bridge_no_actions_returns_failure passed")


def test_gui_bridge_actions_from_kwargs():
    """actions 通过 kwargs 传入。"""
    bridge = GUIBridge()
    task = Task.from_text("test")
    custom_actions = [{"action": "click", "x": 100, "y": 200}]
    actions = bridge._get_actions(task, actions=custom_actions)
    assert actions == custom_actions
    print("✅ test_gui_bridge_actions_from_kwargs passed")


def test_gui_bridge_actions_from_context():
    """actions 通过 task.context 传入。"""
    bridge = GUIBridge()
    task = Task.from_text("test", context={"actions": [{"action": "type", "text": "hello"}]})
    actions = bridge._get_actions(task)
    assert len(actions) == 1
    assert actions[0]["action"] == "type"
    print("✅ test_gui_bridge_actions_from_context passed")


def test_gui_bridge_actions_from_json():
    """actions 通过 JSON 格式的 task.content 传入。"""
    bridge = GUIBridge()
    json_content = '[{"action": "move", "x": 10, "y": 20}, {"action": "screenshot"}]'
    task = Task.from_text(json_content)
    actions = bridge._get_actions(task)
    assert len(actions) == 2
    assert actions[0]["action"] == "move"
    print("✅ test_gui_bridge_actions_from_json passed")


def test_gui_bridge_check_available_returns_bool():
    """check_available() 返回 bool（不依赖 pyautogui 安装）。"""
    bridge = GUIBridge()
    result = bridge.check_available()
    assert isinstance(result, bool)
    print("✅ test_gui_bridge_check_available_returns_bool passed")


def test_gui_bridge_pyautogui_not_installed_returns_failure():
    """pyautogui 未安装时 run() 返回明确的错误信息。"""
    bridge = GUIBridge()
    task = Task.from_text("test", context={"actions": [{"action": "click", "x": 1, "y": 1}]})
    result = bridge.run(task)
    if not bridge.check_available():
        assert result.success is False
        assert "not installed" in result.error.lower()
    print("✅ test_gui_bridge_pyautogui_not_installed_returns_failure passed")


# ─── 3. RuntimeRegistry ───

def test_runtime_registry_default_has_builtin_types():
    """RuntimeRegistry.default() 自动注册内置 Runtime 类型。"""
    reg = RuntimeRegistry.default()
    types = reg.available_types()
    assert "fake" in types
    assert "cli" in types
    assert "api" in types
    assert "gui" in types
    assert "browser" in types
    print("✅ test_runtime_registry_default_has_builtin_types passed")


def test_runtime_registry_create_bridge_fake():
    """create_bridge('fake') 创建 FakeBridge 实例。"""
    reg = RuntimeRegistry.default()
    bridge = reg.create_bridge("fake", response="test response")
    assert isinstance(bridge, FakeBridge)
    assert bridge.response == "test response"
    print("✅ test_runtime_registry_create_bridge_fake passed")


def test_runtime_registry_create_bridge_cli():
    """create_bridge('cli') 创建 CLIBridge 实例。"""
    reg = RuntimeRegistry.default()
    bridge = reg.create_bridge("cli", command="echo")
    assert isinstance(bridge, CLIBridge)
    assert bridge.command == "echo"
    print("✅ test_runtime_registry_create_bridge_cli passed")


def test_runtime_registry_create_bridge_browser():
    """create_bridge('browser') 创建 BrowserBridge 实例。"""
    reg = RuntimeRegistry.default()
    bridge = reg.create_bridge("browser", headless=False)
    assert isinstance(bridge, BrowserBridge)
    assert bridge.headless is False
    print("✅ test_runtime_registry_create_bridge_browser passed")


def test_runtime_registry_create_bridge_gui():
    """create_bridge('gui') 创建 GUIBridge 实例。"""
    reg = RuntimeRegistry.default()
    bridge = reg.create_bridge("gui", app_name="Marvis")
    assert isinstance(bridge, GUIBridge)
    assert bridge.app_name == "Marvis"
    print("✅ test_runtime_registry_create_bridge_gui passed")


def test_runtime_registry_register_custom():
    """注册自定义 Runtime 类型。"""
    reg = RuntimeRegistry()

    class CustomBridge(Bridge):
        def __init__(self, **kwargs):
            self.config = kwargs
        def run(self, task, **kwargs):
            return BridgeResult(success=True, output="custom")
        def check_available(self):
            return True

    reg.register("custom", CustomBridge, description="custom runtime", timeout=60)
    assert "custom" in reg.available_types()

    runtime = reg.get("custom")
    assert runtime is not None
    assert runtime.name == "custom"
    assert runtime.description == "custom runtime"
    assert runtime.default_config["timeout"] == 60

    bridge = reg.create_bridge("custom", timeout=120)
    assert isinstance(bridge, CustomBridge)
    print("✅ test_runtime_registry_register_custom passed")


def test_runtime_registry_unregister():
    """注销 Runtime 类型。"""
    reg = RuntimeRegistry()

    class TempBridge(Bridge):
        def __init__(self, **kwargs):
            pass
        def run(self, task, **kwargs):
            return BridgeResult(success=True, output="temp")
        def check_available(self):
            return True

    reg.register("temp", TempBridge)
    assert "temp" in reg.available_types()

    assert reg.unregister("temp") is True
    assert "temp" not in reg.available_types()
    assert reg.unregister("temp") is False
    print("✅ test_runtime_registry_unregister passed")


def test_runtime_registry_create_unregistered_raises():
    """创建未注册的 Runtime 应抛出 ValueError。"""
    reg = RuntimeRegistry()
    try:
        reg.create_bridge("nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "not registered" in str(e)
    print("✅ test_runtime_registry_create_unregistered_raises passed")


def test_runtime_registry_check_available():
    """check_available() 返回 bool。"""
    reg = RuntimeRegistry.default()
    # fake runtime should be available
    assert reg.check_available("fake") is True
    # browser might not be available (no Playwright)
    result = reg.check_available("browser")
    assert isinstance(result, bool)
    print("✅ test_runtime_registry_check_available passed")


def test_runtime_registry_available_runtimes():
    """available_runtimes() 返回可用列表。"""
    reg = RuntimeRegistry.default()
    available = reg.available_runtimes()
    assert isinstance(available, list)
    assert "fake" in available
    print("✅ test_runtime_registry_available_runtimes passed")


def test_runtime_registry_all():
    """all() 返回所有 Runtime 描述符。"""
    reg = RuntimeRegistry.default()
    runtimes = reg.all()
    assert len(runtimes) >= 5
    assert all(isinstance(r, Runtime) for r in runtimes)
    print("✅ test_runtime_registry_all passed")


# ─── 4. FakeBrowserProvider 契约 ───

def test_fake_browser_provider_inherits_provider():
    """FakeBrowserProvider 必须继承 Provider。"""
    from providers.fake_browser.provider import FakeBrowserProvider
    assert issubclass(FakeBrowserProvider, Provider)
    print("✅ test_fake_browser_provider_inherits_provider passed")


def test_fake_browser_provider_metadata():
    """FakeBrowserProvider 的 metadata 正确。"""
    from providers.fake_browser.provider import FakeBrowserProvider
    md = FakeBrowserProvider.metadata
    assert md.name == "fake_browser"
    assert "browser.navigate" in md.capabilities
    assert "browser.screenshot" in md.capabilities
    print("✅ test_fake_browser_provider_metadata passed")


def test_fake_browser_provider_uses_browser_bridge():
    """FakeBrowserProvider 使用 BrowserBridge。"""
    from providers.fake_browser.provider import FakeBrowserProvider
    assert isinstance(FakeBrowserProvider.bridge, BrowserBridge)
    print("✅ test_fake_browser_provider_uses_browser_bridge passed")


def test_fake_browser_provider_available_returns_bool():
    """available() 返回 bool。"""
    from providers.fake_browser.provider import FakeBrowserProvider
    provider = FakeBrowserProvider()
    result = provider.available()
    assert isinstance(result, bool)
    print("✅ test_fake_browser_provider_available_returns_bool passed")


def test_fake_browser_provider_no_execute():
    """FakeBrowserProvider 不得有 execute() 方法。"""
    from providers.fake_browser.provider import FakeBrowserProvider
    provider = FakeBrowserProvider()
    assert not hasattr(provider, "execute")
    print("✅ test_fake_browser_provider_no_execute passed")


def test_fake_browser_provider_estimate():
    """estimate() 返回合法 dict。"""
    from providers.fake_browser.provider import FakeBrowserProvider
    provider = FakeBrowserProvider()
    task = Task.from_text("test")
    est = provider.estimate(task)
    assert isinstance(est, dict)
    assert "duration_ms_est" in est
    assert "timeout" in est
    print("✅ test_fake_browser_provider_estimate passed")


def test_fake_browser_provider_router_integration():
    """FakeBrowserProvider 可以注册到 Router 并被路由。"""
    from providers.fake_browser.provider import FakeBrowserProvider

    reg = CapabilityRegistry()
    reg.register(FakeBrowserProvider())
    router = Router(reg)

    task = Task.from_text("打开网页")
    result = router.execute(task)

    # Provider 可能不可用（Playwright 未安装），但不应崩溃
    assert isinstance(result, Result)
    print("✅ test_fake_browser_provider_router_integration passed")


# ─── 5. Bridge 继承关系综合验证 ───

def test_all_bridges_inherit_base():
    """所有 Bridge 子类都继承 Bridge。"""
    for cls in [FakeBridge, CLIBridge, APIBridge, GUIBridge, BrowserBridge]:
        assert issubclass(cls, Bridge), f"{cls.__name__} does not inherit Bridge"
    print("✅ test_all_bridges_inherit_base passed")


def test_all_bridges_have_required_methods():
    """所有 Bridge 子类都实现了 run() 和 check_available()。"""
    for cls in [FakeBridge, CLIBridge, APIBridge, GUIBridge, BrowserBridge]:
        assert hasattr(cls, "run"), f"{cls.__name__} missing run()"
        assert hasattr(cls, "check_available"), f"{cls.__name__} missing check_available()"
    print("✅ test_all_bridges_have_required_methods passed")


if __name__ == "__main__":
    # BrowserBridge
    test_browser_bridge_inherits_bridge()
    test_browser_bridge_has_run_and_check_available()
    test_browser_bridge_no_actions_returns_failure()
    test_browser_bridge_url_in_content_auto_actions()
    test_browser_bridge_actions_from_kwargs()
    test_browser_bridge_actions_from_context()
    test_browser_bridge_actions_from_json()
    test_browser_bridge_check_available_returns_bool()
    test_browser_bridge_playwright_not_installed_returns_failure()

    # GUIBridge
    test_gui_bridge_inherits_bridge()
    test_gui_bridge_has_run_and_check_available()
    test_gui_bridge_no_actions_returns_failure()
    test_gui_bridge_actions_from_kwargs()
    test_gui_bridge_actions_from_context()
    test_gui_bridge_actions_from_json()
    test_gui_bridge_check_available_returns_bool()
    test_gui_bridge_pyautogui_not_installed_returns_failure()

    # RuntimeRegistry
    test_runtime_registry_default_has_builtin_types()
    test_runtime_registry_create_bridge_fake()
    test_runtime_registry_create_bridge_cli()
    test_runtime_registry_create_bridge_browser()
    test_runtime_registry_create_bridge_gui()
    test_runtime_registry_register_custom()
    test_runtime_registry_unregister()
    test_runtime_registry_create_unregistered_raises()
    test_runtime_registry_check_available()
    test_runtime_registry_available_runtimes()
    test_runtime_registry_all()

    # FakeBrowserProvider
    test_fake_browser_provider_inherits_provider()
    test_fake_browser_provider_metadata()
    test_fake_browser_provider_uses_browser_bridge()
    test_fake_browser_provider_available_returns_bool()
    test_fake_browser_provider_no_execute()
    test_fake_browser_provider_estimate()
    test_fake_browser_provider_router_integration()

    # 综合
    test_all_bridges_inherit_base()
    test_all_bridges_have_required_methods()

    print("\n🎉 All Runtime tests passed!")
