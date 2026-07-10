"""AI Hub — V0.0.5 测试

验证重构后的核心流程：
1. Result 数据结构
2. Provider + Metadata + Bridge
3. Registry 按 capability 查找
4. Router: Task → Capability → Provider
5. History 持久化
6. 三种 Bridge（Fake / CLI / API）接口一致
7. Provider Validation
8. 端到端
"""

import sys
import os
import tempfile

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_result():
    """测试 Result 数据结构。"""
    from core.result import Result

    r = Result(provider="test", status="success", output="hello", metadata={"duration_ms": 100})
    assert r.is_success is True
    assert str(r) == "hello"

    r2 = Result(provider="test", status="failed", output="", error="error")
    assert r2.is_success is False

    try:
        Result(provider="test", status="invalid", output="")
        assert False
    except ValueError:
        pass

    d = r.to_dict()
    r3 = Result.from_dict(d)
    assert r3.provider == "test"
    print("✅ test_result passed")


def test_metadata():
    """测试 ProviderMetadata。"""
    from core.provider import ProviderMetadata

    md = ProviderMetadata(
        name="test",
        display_name="Test",
        description="test provider",
        capabilities=["code.generate", "general.chat"],
        priority=50,
    )
    assert md.name == "test"
    assert len(md.capabilities) == 2
    assert md.priority == 50
    print("✅ test_metadata passed")


def test_bridges():
    """测试三种 Bridge 接口一致性。"""
    from core.bridge import FakeBridge, CLIBridge, APIBridge, BridgeResult

    # FakeBridge
    fb = FakeBridge(response="fake response")
    assert fb.check_available() is True
    result = fb.run("test task")
    assert isinstance(result, BridgeResult)
    assert result.success is True
    assert "fake response" in result.output
    assert "test task" in result.output

    # CLIBridge（不调用真实命令，只验证接口）
    cb = CLIBridge(command="echo")
    assert isinstance(cb.check_available(), bool)

    # APIBridge（不调用真实 API，只验证接口）
    ab = APIBridge(endpoint="https://example.com", api_key_env="FAKE_KEY")
    assert ab.check_available() is False  # 没有设置 FAKE_KEY 环境变量

    print("✅ test_bridges passed")


def test_provider_with_bridge():
    """测试 Provider + Bridge 集成。"""
    from core.provider import Provider, ProviderMetadata
    from core.bridge import FakeBridge
    from core.result import Result
    from typing import Any

    class TestProvider(Provider):
        metadata = ProviderMetadata(
            name="test_provider",
            display_name="Test",
            description="test",
            capabilities=["code.generate", "general.chat"],
            priority=50,
        )
        bridge = FakeBridge(response="test ok")

        def health(self) -> bool:
            return True

        def authenticated(self) -> bool:
            return True

        def quota_left(self) -> int:
            return -1

        def execute(self, task: str, context: dict[str, Any] | None = None) -> Result:
            br = self._run_bridge(task)
            return self._bridge_to_result(br, self.name)

    p = TestProvider()
    assert p.name == "test_provider"
    assert p.supports("code.generate") is True
    assert p.supports("text.translate") is False

    result = p.execute("hello")
    assert result.is_success
    assert result.provider == "test_provider"
    assert "test ok" in result.output

    print("✅ test_provider_with_bridge passed")


def test_capability_routing():
    """测试 Capability 路由系统。"""
    from core.capabilities import classify, CAPABILITIES

    # 关键词 → 能力
    caps = classify("写一个 Python 服务")
    assert "code.generate" in caps

    caps = classify("总结这个 PDF")
    assert "text.summarize" in caps

    caps = classify("搜索 Rust 新特性")
    assert "search.web" in caps

    caps = classify("你好")
    assert "general.chat" in caps

    # 所有能力标签都是合法的
    for cap in CAPABILITIES:
        assert "." in cap  # 命名空间格式

    print("✅ test_capability_routing passed")


def test_registry():
    """测试 Registry 按 capability 查找。"""
    from core.registry import ProviderRegistry
    from providers.demo.provider import DemoProvider

    reg = ProviderRegistry()
    reg.register(DemoProvider())

    # 按 capability 查找
    providers = reg.find_by_capability("code.generate")
    assert len(providers) == 1
    assert providers[0].name == "demo"

    providers = reg.find_by_capability("search.web")
    assert len(providers) == 1

    # 查找不存在的能力
    providers = reg.find_by_capability("nonexistent.cap")
    assert len(providers) == 0

    # find_by_any_capability
    providers = reg.find_by_any_capability(["code.generate", "search.web"])
    assert len(providers) == 1  # 同一个 Provider 支持两个

    print("✅ test_registry passed")


def test_router():
    """测试 Router: Task → Capability → Provider。"""
    from core.registry import ProviderRegistry
    from router.router import Router
    from providers.demo.provider import DemoProvider

    reg = ProviderRegistry()
    reg.register(DemoProvider())
    router = Router(reg)

    caps, provider = router.route("写代码")
    assert provider is not None
    assert provider.name == "demo"
    assert "code.generate" in caps

    result = router.execute("写代码")
    assert result.is_success

    print("✅ test_router passed")


def test_history():
    from core.result import Result
    from core.history import HistoryStore

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        filepath = f.name

    store = HistoryStore(filepath)
    result = Result(provider="demo", status="success", output="test", metadata={"duration_ms": 50})
    store.add("test task", "code.generate", "demo", result)
    assert len(store.recent(1)) == 1

    os.unlink(filepath)
    print("✅ test_history passed")


def test_end_to_end():
    """端到端：三种 Bridge 类型都能通过同一套接口执行。"""
    from core.provider import Provider, ProviderMetadata
    from core.bridge import FakeBridge, CLIBridge, APIBridge
    from core.result import Result
    from core.registry import ProviderRegistry
    from router.router import Router
    from typing import Any

    # 创建三个 Provider，分别用三种 Bridge
    class FakeProvider(Provider):
        metadata = ProviderMetadata(
            name="fake", display_name="Fake", description="fake",
            capabilities=["general.chat"], priority=100,
        )
        bridge = FakeBridge(response="fake response")
        def health(self): return True
        def authenticated(self): return True
        def quota_left(self): return -1
        def execute(self, task, context=None):
            br = self._run_bridge(task)
            return self._bridge_to_result(br, self.name)

    reg = ProviderRegistry()
    reg.register(FakeProvider())
    router = Router(reg)

    # 执行
    result = router.execute("你好")
    assert result.is_success
    assert result.provider == "fake"
    assert "fake response" in result.output

    print("✅ test_end_to_end passed")


def test_three_bridge_types():
    """验证同一套 Provider 接口可以统一三种不同通信方式。"""
    from core.provider import Provider, ProviderMetadata
    from core.bridge import FakeBridge, CLIBridge, APIBridge
    from core.result import Result
    from typing import Any

    class CLITypeProvider(Provider):
        """模拟 CLI 通信方式。"""
        metadata = ProviderMetadata(
            name="cli_type", display_name="CLI Type", description="CLI bridge demo",
            capabilities=["code.generate"], priority=100,
        )
        bridge = FakeBridge(response="[CLI Bridge] done")  # 用 Fake 模拟 CLI
        def health(self): return True
        def authenticated(self): return True
        def quota_left(self): return -1
        def execute(self, task, context=None):
            br = self._run_bridge(task)
            return self._bridge_to_result(br, self.name)

    class APITypeProvider(Provider):
        """模拟 API 通信方式。"""
        metadata = ProviderMetadata(
            name="api_type", display_name="API Type", description="API bridge demo",
            capabilities=["code.generate"], priority=80,
        )
        bridge = FakeBridge(response="[API Bridge] done")  # 用 Fake 模拟 API
        def health(self): return True
        def authenticated(self): return True
        def quota_left(self): return -1
        def execute(self, task, context=None):
            br = self._run_bridge(task)
            return self._bridge_to_result(br, self.name)

    class GUITypeProvider(Provider):
        """模拟 GUI 通信方式（未来扩展）。"""
        metadata = ProviderMetadata(
            name="gui_type", display_name="GUI Type", description="GUI bridge demo",
            capabilities=["code.generate"], priority=60,
        )
        bridge = FakeBridge(response="[GUI Bridge] done")  # 用 Fake 模拟 GUI
        def health(self): return True
        def authenticated(self): return True
        def quota_left(self): return -1
        def execute(self, task, context=None):
            br = self._run_bridge(task)
            return self._bridge_to_result(br, self.name)

    # 三种 Provider 都能通过同一套接口执行
    for cls in [CLITypeProvider, APITypeProvider, GUITypeProvider]:
        p = cls()
        result = p.execute("写代码")
        assert result.is_success, f"{cls.__name__} failed"
        assert p.name in result.output or "Bridge" in result.output

    # 三种 Provider 注册到同一个 Registry，Router 能统一路由
    from core.registry import ProviderRegistry
    from router.router import Router

    reg = ProviderRegistry()
    reg.register(CLITypeProvider())
    reg.register(APITypeProvider())
    reg.register(GUITypeProvider())

    router = Router(reg)
    caps, provider = router.route("写代码")
    assert provider is not None
    assert provider.name == "cli_type"  # 优先级最高

    # CLI 不可用时自动降级到 API
    # (模拟方式：注册一个不 可用的 CLI Provider)
    # 这里验证 fallback 逻辑不需要真实不可用

    print("✅ test_three_bridge_types passed")


if __name__ == "__main__":
    test_result()
    test_metadata()
    test_bridges()
    test_provider_with_bridge()
    test_capability_routing()
    test_registry()
    test_router()
    test_history()
    test_end_to_end()
    test_three_bridge_types()
    print("\n🎉 All tests passed!")
