"""AI Hub — V0.0.6 测试

验证冻结后的核心流程：
1. Result 数据结构（含 artifacts）
2. Task 输入 dataclass
3. Provider + Metadata + Bridge（无 execute()）
4. CapabilityRegistry 按 capability 查找
5. Router: Task → Capability → Provider → select_bridge → bridge.run → Result
6. History 持久化
7. 三种 Bridge（Fake / CLI / API）接口一致
8. GUIBridge / BrowserBridge 接口预留
9. 端到端
10. Provider Validation
"""

import sys
import os
import tempfile

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_result():
    """测试 Result 数据结构（含 artifacts）。"""
    from core.result import Result

    r = Result(provider="test", status="success", output="hello", metadata={"duration_ms": 100})
    assert r.is_success is True
    assert r.artifacts == []
    assert str(r) == "hello"

    r2 = Result(
        provider="test", status="success", output="done",
        artifacts=["/tmp/screenshot.png", "/tmp/report.pdf"]
    )
    assert len(r2.artifacts) == 2
    assert "screenshot.png" in str(r2)

    r3 = Result(provider="test", status="failed", output="", error="error")
    assert r3.is_success is False

    try:
        Result(provider="test", status="invalid", output="")
        assert False
    except ValueError:
        pass

    d = r.to_dict()
    assert "artifacts" in d
    r4 = Result.from_dict(d)
    assert r4.provider == "test"

    print("✅ test_result passed")


def test_task():
    """测试 Task 输入 dataclass。"""
    from core.task import Task

    t = Task.from_text("写一个 Python 服务")
    assert t.content == "写一个 Python 服务"
    assert t.task_id  # 自动生成
    assert "code.generate" in t.capabilities  # 自动识别

    t2 = Task(content="总结这个 PDF", task_id="custom-id")
    assert t2.task_id == "custom-id"
    assert "text.summarize" in t2.capabilities

    t3 = Task.from_text("搜索 Rust 新特性", artifacts=["/tmp/rust.pdf"])
    assert t3.artifacts == ["/tmp/rust.pdf"]
    assert "search.web" in t3.capabilities

    d = t.to_dict()
    assert "task_id" in d
    assert "capabilities" in d

    print("✅ test_task passed")


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
    """测试 Bridge 接口一致性（含 GUI/Browser 预留）。"""
    from core.bridge import FakeBridge, CLIBridge, APIBridge, GUIBridge, BrowserBridge, BridgeResult
    from core.task import Task

    task = Task.from_text("test task")

    # FakeBridge
    fb = FakeBridge(response="fake response")
    assert fb.check_available() is True
    result = fb.run(task)
    assert isinstance(result, BridgeResult)
    assert result.success is True
    assert "fake response" in result.output

    # CLIBridge
    cb = CLIBridge(command="echo")
    assert isinstance(cb.check_available(), bool)

    # APIBridge
    ab = APIBridge(endpoint="https://example.com", api_key_env="FAKE_KEY")
    assert ab.check_available() is False

    # GUIBridge（pyautogui 可能未安装）
    gb = GUIBridge(app_name="Marvis")
    assert isinstance(gb.check_available(), bool)
    gr = gb.run(task)
    assert gr.success is False
    assert gr.error is not None

    # BrowserBridge（Playwright 可能未安装）
    bb = BrowserBridge(url="https://claude.ai")
    assert isinstance(bb.check_available(), bool)
    br = bb.run(task)
    assert br.success is False
    assert br.error is not None

    print("✅ test_bridges passed")


def test_provider_no_execute():
    """测试 Provider 没有 execute() 方法。"""
    from core.provider import Provider, ProviderMetadata
    from core.bridge import FakeBridge
    from core.task import Task

    class TestProvider(Provider):
        metadata = ProviderMetadata(
            name="test_provider",
            display_name="Test",
            description="test",
            capabilities=["code.generate", "general.chat"],
            priority=50,
        )
        bridge = FakeBridge(response="test ok")

        def health(self): return True
        def authenticated(self): return True
        def quota_left(self): return -1

    p = TestProvider()
    assert p.name == "test_provider"
    assert p.supports("code.generate") is True
    assert p.supports("text.translate") is False

    # Provider 没有 execute() 方法
    assert not hasattr(p, "execute")

    # select_bridge 返回 Bridge 实例
    task = Task.from_text("hello")
    bridge = p.select_bridge(task)
    assert bridge is p.bridge

    print("✅ test_provider_no_execute passed")


def test_capability_routing():
    """测试 Capability 路由系统。"""
    from core.capabilities import classify, CAPABILITIES

    caps = classify("写一个 Python 服务")
    assert "code.generate" in caps

    caps = classify("总结这个 PDF")
    assert "text.summarize" in caps

    caps = classify("搜索 Rust 新特性")
    assert "search.web" in caps

    caps = classify("你好")
    assert "general.chat" in caps

    for cap in CAPABILITIES:
        assert "." in cap

    print("✅ test_capability_routing passed")


def test_registry():
    """测试 CapabilityRegistry。"""
    from core.registry import CapabilityRegistry
    from providers.demo.provider import DemoProvider

    reg = CapabilityRegistry()
    reg.register(DemoProvider())

    providers = reg.find_by_capability("code.generate")
    assert len(providers) == 1
    assert providers[0].name == "demo"

    providers = reg.find_by_capability("nonexistent.cap")
    assert len(providers) == 0

    providers = reg.find_by_any_capability(["code.generate", "search.web"])
    assert len(providers) == 1

    print("✅ test_registry passed")


def test_router():
    """测试 Router: Task → Capability → select_bridge → bridge.run → Result。"""
    from core.registry import CapabilityRegistry
    from router.router import Router
    from core.task import Task
    from providers.demo.provider import DemoProvider

    reg = CapabilityRegistry()
    reg.register(DemoProvider())
    router = Router(reg)

    task = Task.from_text("写代码")
    provider = router.route(task)
    assert provider is not None
    assert provider.name == "demo"

    # Provider 没有 execute()，Router 调 select_bridge + bridge.run
    assert not hasattr(provider, "execute")

    result = router.execute(task)
    assert result.is_success
    assert result.provider == "demo"
    assert "bridge" in result.metadata  # Router 记录了用的哪个 Bridge

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
    """端到端：Task → Router → Provider.select_bridge → Bridge.run → Result。"""
    from core.provider import Provider, ProviderMetadata
    from core.bridge import FakeBridge
    from core.registry import CapabilityRegistry
    from router.router import Router
    from core.task import Task

    class FakeProvider(Provider):
        metadata = ProviderMetadata(
            name="fake", display_name="Fake", description="fake",
            capabilities=["general.chat"], priority=100,
        )
        bridge = FakeBridge(response="fake response")
        def health(self): return True
        def authenticated(self): return True
        def quota_left(self): return -1

    reg = CapabilityRegistry()
    reg.register(FakeProvider())
    router = Router(reg)

    task = Task.from_text("你好")
    result = router.execute(task)
    assert result.is_success
    assert result.provider == "fake"
    assert "fake response" in result.output
    assert result.metadata["bridge"] == "FakeBridge"

    print("✅ test_end_to_end passed")


def test_three_bridge_types():
    """验证同一套 Provider 接口可以统一三种不同通信方式（无 execute()）。"""
    from core.provider import Provider, ProviderMetadata
    from core.bridge import FakeBridge
    from core.registry import CapabilityRegistry
    from router.router import Router
    from core.task import Task

    class CLITypeProvider(Provider):
        metadata = ProviderMetadata(
            name="cli_type", display_name="CLI Type", description="CLI bridge demo",
            capabilities=["code.generate"], priority=100,
        )
        bridge = FakeBridge(response="[CLI Bridge] done")
        def health(self): return True
        def authenticated(self): return True
        def quota_left(self): return -1

    class APITypeProvider(Provider):
        metadata = ProviderMetadata(
            name="api_type", display_name="API Type", description="API bridge demo",
            capabilities=["code.generate"], priority=80,
        )
        bridge = FakeBridge(response="[API Bridge] done")
        def health(self): return True
        def authenticated(self): return True
        def quota_left(self): return -1

    class GUITypeProvider(Provider):
        metadata = ProviderMetadata(
            name="gui_type", display_name="GUI Type", description="GUI bridge demo",
            capabilities=["code.generate"], priority=60,
        )
        bridge = FakeBridge(response="[GUI Bridge] done")
        def health(self): return True
        def authenticated(self): return True
        def quota_left(self): return -1

    # 三种 Provider 都没有 execute()
    for cls in [CLITypeProvider, APITypeProvider, GUITypeProvider]:
        p = cls()
        assert not hasattr(p, "execute"), f"{cls.__name__} should not have execute()"

    # 三种 Provider 注册到同一个 Registry，Router 统一路由和执行
    reg = CapabilityRegistry()
    reg.register(CLITypeProvider())
    reg.register(APITypeProvider())
    reg.register(GUITypeProvider())

    router = Router(reg)
    task = Task.from_text("写代码")
    provider = router.route(task)
    assert provider is not None
    assert provider.name == "cli_type"  # 优先级最高

    result = router.execute(task)
    assert result.is_success
    assert result.metadata["bridge"] == "FakeBridge"

    print("✅ test_three_bridge_types passed")


def test_artifacts_flow():
    """测试 artifacts 在整个链路中的传递。"""
    from core.bridge import FakeBridge, BridgeResult
    from core.task import Task

    # Task 携带输入 artifacts
    task = Task.from_text("分析这个 PDF", artifacts=["/tmp/report.pdf"])
    assert task.artifacts == ["/tmp/report.pdf"]

    # Bridge 也可以产出 artifacts
    class ArtifactsBridge(FakeBridge):
        def run(self, task, **kwargs):
            return BridgeResult(
                success=True,
                output="analysis done",
                artifacts=["/tmp/summary.md"],
                duration_ms=10,
            )

    from core.provider import Provider, ProviderMetadata
    from core.registry import CapabilityRegistry
    from router.router import Router

    class AnalysisProvider(Provider):
        metadata = ProviderMetadata(
            name="analysis", display_name="Analysis", description="",
            capabilities=["text.analyze", "text.summarize"], priority=90,
        )
        bridge = ArtifactsBridge()
        def health(self): return True
        def authenticated(self): return True
        def quota_left(self): return -1

    reg = CapabilityRegistry()
    reg.register(AnalysisProvider())
    router = Router(reg)

    result = router.execute(task)
    assert result.is_success
    assert len(result.artifacts) == 1
    assert result.artifacts[0] == "/tmp/summary.md"

    print("✅ test_artifacts_flow passed")


if __name__ == "__main__":
    test_result()
    test_task()
    test_metadata()
    test_bridges()
    test_provider_no_execute()
    test_capability_routing()
    test_registry()
    test_router()
    test_history()
    test_end_to_end()
    test_three_bridge_types()
    test_artifacts_flow()
    print("\n🎉 All tests passed!")
