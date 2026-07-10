"""AI Hub — Skeleton 测试

验证 V0.0 骨架的核心流程：
1. Provider 接口可以正常继承
2. Result 格式正确
3. Registry 注册和查询
4. Router 规则路由
5. CLI 端到端
"""

import sys
import os

# Windows 控制台编码修复
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_result():
    """测试 Result 数据结构。"""
    from core.result import Result

    # 正常创建
    r = Result(
        provider="test",
        status="success",
        output="hello",
        metadata={"duration_ms": 100},
    )
    assert r.is_success is True
    assert str(r) == "hello"

    # 失败状态
    r2 = Result(
        provider="test",
        status="failed",
        output="",
        error="something went wrong",
    )
    assert r2.is_success is False
    assert "failed" in str(r2)

    # 非法 status
    try:
        Result(provider="test", status="invalid", output="")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

    # 序列化
    d = r.to_dict()
    r3 = Result.from_dict(d)
    assert r3.provider == "test"
    assert r3.status == "success"

    print("✅ test_result passed")


def test_provider_interface():
    """测试 Provider 基类可以被继承。"""
    from core.provider import Provider
    from providers.demo.provider import DemoProvider

    p = DemoProvider()
    assert isinstance(p, Provider)
    assert p.name == "demo"
    assert p.available() is True
    assert p.quota_left() == -1
    assert p.supports("coding") is True
    assert p.supports("nonexistent") is False

    print("✅ test_provider_interface passed")


def test_registry():
    """测试 Provider Registry。"""
    from core.registry import ProviderRegistry
    from providers.demo.provider import DemoProvider

    reg = ProviderRegistry()
    reg.register(DemoProvider())

    # 查询
    assert reg.get("demo") is not None
    assert reg.get("nonexistent") is None

    # 按任务类型查找
    coding_providers = reg.find_by_task_type("coding")
    assert len(coding_providers) == 1
    assert coding_providers[0].name == "demo"

    # 可用 Provider
    available = reg.find_available("coding")
    assert len(available) == 1

    # 重复注册
    try:
        reg.register(DemoProvider())
        assert False, "Should have raised ValueError"
    except ValueError:
        pass

    print("✅ test_registry passed")


def test_router():
    """测试 Router 规则路由。"""
    from core.registry import ProviderRegistry
    from router.router import Router, classify_task
    from providers.demo.provider import DemoProvider

    reg = ProviderRegistry()
    reg.register(DemoProvider())
    router = Router(reg)

    # 任务分类
    assert classify_task("写一个 Python 服务") == "coding"
    assert classify_task("总结这个 PDF") == "analysis"
    assert classify_task("搜索 Rust 新特性") == "search"
    assert classify_task("你好") == "general"

    # 路由
    task_type, provider = router.route("写代码")
    assert provider is not None
    assert provider.name == "demo"

    # 执行
    result = router.execute("写代码")
    assert result.is_success
    assert result.provider == "demo"

    print("✅ test_router passed")


def test_history():
    """测试历史记录。"""
    import tempfile
    from core.result import Result
    from core.history import HistoryStore

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        filepath = f.name

    store = HistoryStore(filepath)
    result = Result(
        provider="demo",
        status="success",
        output="test output",
        metadata={"duration_ms": 50},
    )

    store.add("test task", "coding", "demo", result)
    records = store.recent(10)
    assert len(records) == 1
    assert records[0]["input"] == "test task"
    assert records[0]["provider"] == "demo"

    os.unlink(filepath)
    print("✅ test_history passed")


def test_end_to_end():
    """端到端测试：模拟 CLI 调用。"""
    from core.registry import ProviderRegistry
    from router.router import Router
    from core.history import HistoryStore
    from providers.demo.provider import DemoProvider
    import tempfile

    reg = ProviderRegistry()
    reg.register(DemoProvider())
    router = Router(reg)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        hist_path = f.name

    history = HistoryStore(hist_path)

    # 模拟用户输入
    task = "写一个 Python HTTP 服务"
    task_type, provider = router.route(task)
    assert provider is not None

    result = provider.execute(task)
    assert result.is_success
    assert "Hello AI Hub" in result.output

    history.add(task, task_type, provider.name, result)
    assert len(history.recent(1)) == 1

    os.unlink(hist_path)
    print("✅ test_end_to_end passed")


if __name__ == "__main__":
    test_result()
    test_provider_interface()
    test_registry()
    test_router()
    test_history()
    test_end_to_end()
    print("\n🎉 All tests passed!")
