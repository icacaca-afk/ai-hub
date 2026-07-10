# AI Hub — Stub Provider
#
# 用途：架构验证专用。不模拟任何真实平台。
# 目标：证明"第二个 Provider 接入，core/ 和 bridge.py 零修改"这条 KPI 成立。
#
# 关键约束：本文件**禁止 import core/bridge.py 之外的任何 core/* 内部模块**。
# 也禁止重新实现 Bridge.run()。必须复用 CLIBridge。
#
# ADR: docs/adr/0002-stub-provider.md

from __future__ import annotations

import os
import platform
from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge


# Stub 使用本仓库自带的 tools/fake_runtime.py 作为假 Runtime
# 跨平台、零依赖（除了 Python 本身）、可预测行为
# 它模拟一个真的 CLI 工具：读参数、输出文本、exit 0
_HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FAKE_RUNTIME = os.path.join(_HERE, "tools", "fake_runtime.py")


def _pick_command() -> str:
    return "python"


def _command_template() -> str:
    """CLIBridge 的 command_template 格式。

    Windows: python <abs_path> {task}
    POSIX:   python3 <abs_path> {task}

    注意：使用绝对路径，因为 subprocess 不一定有 cwd。
    """
    py = "python" if platform.system() == "Windows" else "python3"
    return f'{py} "{_FAKE_RUNTIME}" {{task}}'


class StubProvider(Provider):
    """Stub Provider — 架构验证专用，不用于生产。

    Bridge: CLIBridge
    目标：证明零修改 core/ + bridge.py 即可接入新 Provider。
    """

    metadata = ProviderMetadata(
        name="stub",
        display_name="Stub (Architecture Probe)",
        description=(
            "架构验证专用 Provider。运行一个本地 echo 命令，"
            "证明第二个 Provider 接入不需要修改 core/ 或 bridge.py。"
        ),
        version="0.0.1",
        capabilities=[
            "code.generate",
            "text.summarize",
            "text.translate",
            "general.chat",
        ],
        priority=10,  # 最低，演示降级链
        fallback=["demo"],
        quota_type="none",
        quota_total=-1,
        quota_auto_detect=False,
    )

    # 关键：直接复用 CLIBridge，**不复用 Gemini 的 command_template/env 写法以外的任何东西**
    # Stub 不需要 env（echo 不认证），但需要自定义 command_template（cmd 的语法特殊）
    # 这正好证明 CLIBridge 的 command_template 是一等公民，不是 Gemini 特供。
    bridge = CLIBridge(
        command=_pick_command(),
        command_template=_command_template(),
        version_command="python --version",  # 检查 python 是否可用
        timeout=10,
    )

    def health(self) -> bool:
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        # Stub 不需要认证——任何"已就绪"状态都算通过
        return self.health()

    def quota_left(self) -> int:
        return -1
