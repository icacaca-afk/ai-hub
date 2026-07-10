# AI Hub — OpenAI API Provider（使用 APIBridge）
#
# 通信方式：HTTP API (OpenAI Chat Completions)
# Bridge: APIBridge
#
# 环境变量：OPENAI_API_KEY
# 可选：OPENAI_MODEL（默认 gpt-3.5-turbo）

from __future__ import annotations

import os

from core.provider import Provider, ProviderMetadata
from core.bridge import APIBridge


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo")


class OpenAIAPIProvider(Provider):
    """OpenAI API Provider，使用 APIBridge。

    调用 OpenAI Chat Completions API。

    环境变量：
        OPENAI_API_KEY: OpenAI API 密钥
        OPENAI_MODEL: 模型名称（默认 gpt-3.5-turbo）
    """

    metadata = ProviderMetadata(
        name="openai_api",
        display_name="OpenAI API",
        description="OpenAI Chat Completions API",
        version="0.1.0",
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
        body_template={
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "user", "content": "{task}"}
            ],
            "temperature": 0.7,
        },
        response_extractor="choices[0].message.content",
        health_endpoint="/v1/models",
    )

    def health(self) -> bool:
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        return bool(OPENAI_API_KEY)

    def quota_left(self) -> int:
        return -1 if self.authenticated() else 0
