# AI Hub — Provider Validation Script
#
# 验证 Provider 是否符合接口规范。
# 可在 GitHub Action 中自动运行，验证每个 PR 的 Provider。
#
# 检查项：
#   ✓ metadata 定义正确
#   ✓ capabilities 是合法标签
#   ✓ bridge 已设置
#   ✓ available() 返回 bool
#   ✓ execute() 返回 Result
#   ✓ Result 格式正确
#   ✓ 异常处理（执行失败时不崩溃）

from __future__ import annotations

import sys
import os
import traceback

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.provider import Provider, ProviderMetadata
from core.bridge import Bridge
from core.result import Result
from core.capabilities import CAPABILITIES


# 颜色输出
def ok(msg: str):
    print(f"  ✅ {msg}")

def fail(msg: str):
    print(f"  ❌ {msg}")

def warn(msg: str):
    print(f"  ⚠️  {msg}")


def validate_provider(provider_cls: type[Provider]) -> bool:
    """验证一个 Provider 类是否符合规范。"""
    cls_name = provider_cls.__name__
    print(f"\n{'='*50}")
    print(f"Validating: {cls_name}")
    print(f"{'='*50}")

    passed = True

    # 1. 检查 metadata
    print("\n[1/7] Metadata")
    metadata = getattr(provider_cls, "metadata", None)
    if not isinstance(metadata, ProviderMetadata):
        fail("metadata is not a ProviderMetadata instance")
        return False

    if not metadata.name:
        fail("metadata.name is empty")
        passed = False
    else:
        ok(f"name = {metadata.name}")

    if not metadata.display_name:
        fail("metadata.display_name is empty")
        passed = False
    else:
        ok(f"display_name = {metadata.display_name}")

    if not metadata.description:
        warn("metadata.description is empty")
    else:
        ok(f"description = {metadata.description}")

    if not metadata.capabilities:
        fail("metadata.capabilities is empty")
        passed = False
    else:
        # 检查能力标签是否合法
        for cap in metadata.capabilities:
            if cap not in CAPABILITIES:
                fail(f"unknown capability: {cap}")
                passed = False
            else:
                ok(f"capability: {cap}")

    if metadata.priority < 0 or metadata.priority > 100:
        warn(f"priority out of recommended range [0-100]: {metadata.priority}")

    # 2. 检查 bridge
    print("\n[2/7] Bridge")
    bridge = getattr(provider_cls, "bridge", None)
    if not isinstance(bridge, Bridge):
        fail("bridge is not a Bridge instance")
        return False
    ok(f"bridge = {type(bridge).__name__}")

    # 3. 实例化
    print("\n[3/7] Instantiation")
    try:
        provider = provider_cls()
        ok("instantiated successfully")
    except Exception as e:
        fail(f"instantiation failed: {e}")
        return False

    # 4. 检查 available()
    print("\n[4/7] available()")
    try:
        result = provider.available()
        if isinstance(result, bool):
            ok(f"available() = {result}")
        else:
            fail(f"available() returned {type(result).__name__}, expected bool")
            passed = False
    except Exception as e:
        fail(f"available() raised: {e}")
        passed = False

    # 5. 检查 quota_left()
    print("\n[5/7] quota_left()")
    try:
        quota = provider.quota_left()
        if isinstance(quota, int):
            ok(f"quota_left() = {quota}")
        else:
            fail(f"quota_left() returned {type(quota).__name__}, expected int")
            passed = False
    except Exception as e:
        fail(f"quota_left() raised: {e}")
        passed = False

    # 6. 检查 execute()
    print("\n[6/7] execute()")
    try:
        result = provider.execute("test task")
        if not isinstance(result, Result):
            fail(f"execute() returned {type(result).__name__}, expected Result")
            passed = False
        else:
            ok(f"execute() → Result(status={result.status})")
            if not result.provider:
                fail("Result.provider is empty")
                passed = False
            if result.status not in ("success", "failed", "timeout", "partial"):
                fail(f"Result.status is invalid: {result.status}")
                passed = False
    except Exception as e:
        fail(f"execute() raised: {e}")
        traceback.print_exc()
        passed = False

    # 7. 检查 supports()
    print("\n[7/7] supports()")
    try:
        for cap in metadata.capabilities:
            if not provider.supports(cap):
                fail(f"supports({cap}) returned False")
                passed = False
        if provider.supports("nonexistent.capability"):
            fail("supports('nonexistent.capability') returned True")
            passed = False
        else:
            ok("supports() works correctly")
    except Exception as e:
        fail(f"supports() raised: {e}")
        passed = False

    # 结果
    print(f"\n{'─'*50}")
    if passed:
        print(f"✅ {cls_name} PASSED")
    else:
        print(f"❌ {cls_name} FAILED")
    print(f"{'─'*50}")

    return passed


def main():
    """验证所有已注册的 Provider。"""
    from providers.demo.provider import DemoProvider

    providers_to_validate = [
        DemoProvider,
    ]

    # 如果有更多 Provider，加入列表
    try:
        from providers.qoder.provider import QoderProvider
        providers_to_validate.append(QoderProvider)
    except ImportError:
        pass

    try:
        from providers.gemini.provider import GeminiCLIProvider
        providers_to_validate.append(GeminiCLIProvider)
    except ImportError:
        pass

    try:
        from providers.openai_api.provider import OpenAIAPIProvider
        providers_to_validate.append(OpenAIAPIProvider)
    except ImportError:
        pass

    all_passed = True
    for cls in providers_to_validate:
        if not validate_provider(cls):
            all_passed = False

    print(f"\n{'='*50}")
    if all_passed:
        print("🎉 All providers passed validation!")
        sys.exit(0)
    else:
        print("❌ Some providers failed validation.")
        sys.exit(1)


if __name__ == "__main__":
    main()
