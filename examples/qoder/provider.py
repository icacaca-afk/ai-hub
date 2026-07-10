"""Example: QODER CLI Provider (minimal).

Copy this file, change 4 things:
  1. metadata.name
  2. metadata.capabilities
  3. bridge command + command_template
  4. health/authenticated/quota_left
"""
from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge


class QoderProvider(Provider):
    metadata = ProviderMetadata(
        name="qoder",
        display_name="QODER",
        description="阿里 Agentic 编程平台 (Qoder CN CLI)",
        version="1.0.14",
        capabilities=["code.generate", "code.debug", "code.refactor", "code.review"],
        priority=100,
        fallback=["gemini_cli", "demo"],
        quota_type="daily",
        quota_total=80,
        quota_auto_detect=False,
    )

    bridge = CLIBridge(
        command="qoderclicn",
        command_template='qoderclicn -p "{task}"',
        version_command="qoderclicn --version",
        timeout=300,
    )

    def health(self): return self.bridge.check_available()
    def authenticated(self): return self.health()
    def quota_left(self): return 80
