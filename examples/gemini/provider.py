"""Example: Gemini CLI Provider (minimal).

Copy this file, change 4 things:
  1. metadata.name
  2. metadata.capabilities
  3. bridge command + command_template
  4. health/authenticated/quota_left
"""
import os
from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge


class GeminiCLIProvider(Provider):
    metadata = ProviderMetadata(
        name="gemini_cli",
        display_name="Gemini CLI",
        description="Google Gemini CLI",
        version="0.50.0",
        capabilities=["code.generate", "search.web", "text.summarize", "text.translate", "general.chat"],
        priority=80,
        fallback=["openai_api", "demo"],
        quota_type="none",
        quota_total=-1,
        quota_auto_detect=False,
    )

    bridge = CLIBridge(
        command="gemini",
        command_template='gemini -p "{task}" -o text --yolo --skip-trust',
        version_command="gemini --version",
        timeout=120,
        env={"GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", "")},
    )

    def health(self): return self.bridge.check_available()
    def authenticated(self): return bool(os.environ.get("GEMINI_API_KEY"))
    def quota_left(self): return -1
