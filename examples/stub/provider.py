"""Example: Stub Provider (minimal, for architecture testing).

Copy this file to bootstrap a new CLI Provider.
Replace fake_runtime.py with your real CLI tool.
"""
import os
from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge

_HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FAKE_RUNTIME = os.path.join(_HERE, "tools", "fake_runtime.py")


class StubProvider(Provider):
    metadata = ProviderMetadata(
        name="stub",
        display_name="Stub (Architecture Probe)",
        description="架构验证专用 Provider",
        version="0.0.1",
        capabilities=["code.generate", "text.summarize", "text.translate", "general.chat"],
        priority=10,
        fallback=["demo"],
        quota_type="none",
        quota_total=-1,
        quota_auto_detect=False,
    )

    bridge = CLIBridge(
        command="python",
        command_template=f'python "{_FAKE_RUNTIME}" {{task}}',
        version_command="python --version",
        timeout=10,
    )

    def health(self): return self.bridge.check_available()
    def authenticated(self): return self.health()
    def quota_left(self): return -1
