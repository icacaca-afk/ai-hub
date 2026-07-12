"""Marvis E2E 验证 — 手工 + 自动

GUI 项目的 E2E 测试有硬依赖（必须 Marvis 运行中）。
本文件提供两种模式：

1. 自动模式（Marvis 运行时）：`python tests/test_marvis_e2e.py`
2. 手工模式（任何情况）：`python tests/test_marvis_e2e.py --manual`

使用：
    python tests/test_marvis_e2e.py          # 自动跑（需 Marvis 运行）
    python tests/test_marvis_e2e.py --manual # 打印手工验证步骤
"""
from __future__ import annotations

import sys
import os
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


MANUAL_CHECKLIST = """
============================================================
  Marvis E2E 手工验证清单
============================================================

前置条件：
  [ ] Marvis 桌面应用已启动，主窗口可见
  [ ] pip install uiautomation
  [ ] ai-hub 已安装（python cli/main.py）

步骤 1: 健康检查
  命令:  python cli/main.py status
  预期:  marvis: Available ✅

步骤 2: 冒烟测试
  命令:  python cli/main.py ask "回复 hello"
  预期:  收到 Marvis 的回复文本（如 "hello" 或问候语）
  时间:  < 30 秒

步骤 3: 代码生成
  命令:  python cli/main.py ask "用 Python 写一个反转字符串的函数"
  预期:  收到包含 def reverse_string 的代码

步骤 4: 翻译
  命令:  python cli/main.py ask "把 hello world 翻译成中文"
  预期:  收到中文翻译

步骤 5: Provider 元数据
  命令:  python cli/main.py caps
  预期:  marvis 在列表中，包含 code.generate / general.chat / text.summarize / text.translate

步骤 6: 历史记录
  命令:  python cli/main.py history
  预期:  显示 Marvis 执行的记录

============================================================
  □ 全部通过 → V0.4 收口
  □ 有问题 → 记录到 docs/manual/MARVIS_SETUP.md
============================================================
"""


def check_marvis_running() -> bool:
    """检查 Marvis 是否在运行。"""
    try:
        from providers.marvis.provider import MarvisProvider
        p = MarvisProvider()
        return p.health()
    except Exception:
        return False


def test_e2e_smoke():
    """冒烟测试：Marvis 必须能响应 hello。"""
    from providers.marvis.provider import MarvisProvider
    from core.task import Task

    if not check_marvis_running():
        print("⏭️  Marvis is not running — skipping E2E smoke test")
        print("   启动 Marvis 后运行: python tests/test_marvis_e2e.py")
        return

    p = MarvisProvider()
    task = Task.from_text("回复 hello（只回复 hello 这个词，不要多余文字）")

    bridge = p.select_bridge(task)
    result = bridge.run(task, timeout=60)

    assert result.success, f"Marvis smoke test failed: {result.error}"
    assert "hello" in result.output.lower(), (
        f"Expected 'hello' in output, got: {result.output[:100]}"
    )
    print(f"✅ Marvis E2E smoke: {result.output[:100]} ({result.duration_ms}ms)")


def test_e2e_code_generation():
    """代码生成测试。"""
    from providers.marvis.provider import MarvisProvider
    from core.task import Task

    if not check_marvis_running():
        print("⏭️  Marvis is not running — skipping code gen test")
        return

    p = MarvisProvider()
    task = Task.from_text("写一个 Python 函数 reverse_string(s) 返回反转字符串")

    bridge = p.select_bridge(task)
    result = bridge.run(task, timeout=120)

    assert result.success, f"Marvis code gen failed: {result.error}"
    assert result.output.strip(), "Empty output for code generation"
    print(f"✅ Marvis E2E code gen: {len(result.output)} chars ({result.duration_ms}ms)")


def run_all_auto():
    """自动模式：跑所有 E2E 测试。"""
    print("Marvis E2E — Auto Mode")
    print("=" * 50)

    if not check_marvis_running():
        print("\n❌ Marvis is NOT running.")
        print("   E2E tests require Marvis to be active.")
        print(f"\n{MANUAL_CHECKLIST}")
        sys.exit(1)

    tests = [test_e2e_smoke, test_e2e_code_generation]
    passed = 0
    failed = 0
    skipped = 0

    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"❌ {t.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__} ERROR: {e}")
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"E2E: {passed}/{len(tests)} passed, {failed} failed, {skipped} skipped")

    if failed:
        sys.exit(1)
    else:
        print("🎉 Marvis E2E all passed!")


if __name__ == "__main__":
    if "--manual" in sys.argv:
        print(MANUAL_CHECKLIST)
    else:
        run_all_auto()
