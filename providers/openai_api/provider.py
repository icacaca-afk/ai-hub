# AI Hub — OpenAI API Provider（使用 APIBridge）
#
# 通信方式：HTTP API
# Bridge: APIBridge

from __future__ import annotations

from core.provider import Provider, ProviderMetadata
from core.bridge import APIBridge


class OpenAIAPIProvider(Provider):
    """OpenAI API Provider，使用 APIBridge。

    环境变量：OPENAI_API_KEY
    """

    metadata = ProviderMetadata(
        name="openai_api",
        display_name="OpenAI API",
        description="OpenAI Chat Completions API",
        version="0.0.1",
        capabilities=[
            "code.generate",
            "text.generate",
            "text.summarize",
            "text.translate",
            "general.chat",
        ],
        priority=50,
        fallback=["demo"],
        quota_type="unknown",
        quota_total=-1,
        cost_currency="USD",
        cost_amount=0.01,
        cost_unit="per_call",
    )

    bridge = APIBridge(
        endpoint="https://api.openai.com/v1/chat/completions",
        api_key_env="OPENAI_API_KEY",
        method="POST",
        timeout=300,
    )

    def health(self) -> bool:
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        return self.bridge.check_auth()

    def quota_left(self) -> int:
        return -1 if self.authenticated() else 0
