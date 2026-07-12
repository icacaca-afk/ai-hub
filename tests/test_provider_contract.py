"""
AI Hub — Provider Contract Test (V0.1.1)

目标：
1. 强制所有 Provider 实现统一接口（KPI: 零修改 core/）
2. 在 CI 中作为质量门禁
3. 让"加 Provider"成为填空题而不是开卷考

使用：
    python -m pytest tests/test_provider_contract.py -v
    或
    python tests/test_provider_contract.py
"""

import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.task import Task
from core.result import Result
from core.bridge import BridgeResult


def check_contract(provider_class) -> list[str]:
    """检查一个 Provider 类是否满足 Contract。

    返回：违规项列表（空列表 = 通过）
    """
    errors = []

    # 1. 必须有 metadata
    if not hasattr(provider_class, "metadata"):
        errors.append("missing: metadata (class attribute)")
    else:
        md = provider_class.metadata
        if not hasattr(md, "name") or not md.name:
            errors.append("metadata.name is empty")
        if not hasattr(md, "capabilities") or not md.capabilities:
            errors.append("metadata.capabilities is empty")
        if not hasattr(md, "priority"):
            errors.append("metadata.priority missing")
        if not hasattr(md, "fallback"):
            errors.append("metadata.fallback missing")

    # 2. 必须有 bridge
    if not hasattr(provider_class, "bridge"):
        errors.append("missing: bridge (class attribute)")
    else:
        if not hasattr(provider_class.bridge, "run"):
            errors.append("bridge.run method missing")
        if not hasattr(provider_class.bridge, "check_available"):
            errors.append("bridge.check_available method missing")

    # 3. 必备方法
    for method in ("health", "authenticated", "quota_left"):
        if not hasattr(provider_class, method):
            errors.append(f"missing method: {method}")

    # 4. 不应该有 execute()（V0.0.6 冻结）
    if hasattr(provider_class, "execute"):
        errors.append("legacy: execute() should be removed (V0.0.6)")

    # 5. 实例化测试
    try:
        p = provider_class()
    except Exception as e:
        errors.append(f"instantiation failed: {e}")
        return errors

    # 6. supports() 必须工作
    try:
        supports_code = p.supports("code.generate")
        if not isinstance(supports_code, bool):
            errors.append("supports() did not return bool")
    except Exception as e:
        errors.append(f"supports() failed: {e}")

    # 7. select_bridge() 必须工作
    try:
        task = Task.from_text("hello world")
        bridge = p.select_bridge(task)
        if bridge is None:
            errors.append("select_bridge() returned None")
        elif not isinstance(bridge, type(p.bridge)):
            errors.append(
                f"select_bridge() returned {type(bridge).__name__}, "
                f"expected {type(p.bridge).__name__}"
            )
    except Exception as e:
        errors.append(f"select_bridge() failed: {e}")

    return errors


def test_demo_provider_contract():
    """Demo Provider (FakeBridge) 必须通过 Contract。"""
    from providers.demo.provider import DemoProvider
    errors = check_contract(DemoProvider)
    assert not errors, f"DemoProvider contract violations: {errors}"
    print("✅ test_demo_provider_contract passed")


def test_qoder_provider_contract():
    """QODER Provider (CLIBridge) 必须通过 Contract（即使不可用）。"""
    from providers.qoder.provider import QoderProvider
    errors = check_contract(QoderProvider)
    # 不强制 CLI 可用——QODER CLI 可能没装
    # 只检查接口契约
    assert not errors, f"QoderProvider contract violations: {errors}"
    print("✅ test_qoder_provider_contract passed")


def test_gemini_provider_contract():
    """Gemini Provider (CLIBridge) 必须通过 Contract。"""
    from providers.gemini.provider import GeminiCLIProvider
    errors = check_contract(GeminiCLIProvider)
    assert not errors, f"GeminiCLIProvider contract violations: {errors}"
    print("✅ test_gemini_provider_contract passed")


def test_openai_provider_contract():
    """OpenAI Provider (APIBridge) 必须通过 Contract。"""
    from providers.openai_api.provider import OpenAIAPIProvider
    errors = check_contract(OpenAIAPIProvider)
    assert not errors, f"OpenAIAPIProvider contract violations: {errors}"
    print("✅ test_openai_provider_contract passed")


def test_zero_modification_kpi():
    """KPI: 新增 Provider 不应修改 core/ 和 bridge.py。

    这是一个手动验证的提示，不是自动测试。
    真正的 KPI 在 README 里由人审计。
    """
    # 列出所有 core/ 文件
    core_files = [
        "core/provider.py",
        "core/registry.py",
        "core/result.py",
        "core/task.py",
        "core/capabilities.py",
        "core/bridge.py",
        "router/router.py",
    ]
    print(f"📊 Core files monitored for zero-modification: {len(core_files)}")
    for f in core_files:
        exists = os.path.exists(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), f
        ))
        if not exists:
            print(f"  ⚠️  {f} not found")
    print("✅ Zero-modification KPI registry is set up (manual audit in README)")
    print("   真正的验证：'git diff main -- core/ bridge.py router/' 应为空（除 ADR 显式批准）")


def test_marvis_provider_contract():
    """Marvis Provider (MarvisBridge) 必须通过 Contract。"""
    from providers.marvis.provider import MarvisProvider
    errors = check_contract(MarvisProvider)
    assert not errors, f"MarvisProvider contract violations: {errors}"
    print("✅ test_marvis_provider_contract passed")


def test_capability_metadata_consistency():
    """每个 Provider 声明的 capability 必须存在于 CAPABILITIES 注册表。"""
    from core.capabilities import CAPABILITIES
    from providers.demo.provider import DemoProvider
    from providers.qoder.provider import QoderProvider
    from providers.gemini.provider import GeminiCLIProvider
    from providers.openai_api.provider import OpenAIAPIProvider

    from providers.marvis.provider import MarvisProvider

    providers = [DemoProvider, QoderProvider, GeminiCLIProvider, OpenAIAPIProvider, MarvisProvider]
    for p_class in providers:
        for cap in p_class.metadata.capabilities:
            assert cap in CAPABILITIES, (
                f"{p_class.metadata.name} declares unknown capability '{cap}'. "
                f"Known: {CAPABILITIES}"
            )
    print("✅ test_capability_metadata_consistency passed")


def run_all():
    """手动跑所有 Contract Test。"""
    tests = [
        test_demo_provider_contract,
        test_qoder_provider_contract,
        test_gemini_provider_contract,
        test_openai_provider_contract,
        test_marvis_provider_contract,
        test_zero_modification_kpi,
        test_capability_metadata_consistency,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__} ERROR: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Contract Tests: {len(tests) - failed}/{len(tests)} passed")
    if failed:
        sys.exit(1)
    else:
        print("🎉 All providers satisfy the Contract.")


if __name__ == "__main__":
    run_all()
