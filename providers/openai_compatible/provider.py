# AI Hub — OpenAI Compatible API Provider
#
# 通信方式：HTTP API (OpenAI Compatible)
# Bridge: APIBridge
#
# 支持任何 OpenAI 兼容的 API 端点：
#   - OpenAI API
#   - OpenRouter
#   - Together AI
#   - 本地 Ollama (OpenAI 兼容模式)
#   - 任何其他兼容 /v1/chat/completions 的服务
#
# 环境变量：
#   - OPENAI_COMPATIBLE_API_KEY: API Key
#   - OPENAI_COMPATIBLE_BASE_URL: 基础 URL（默认 https://api.openai.com/v1）
#   - OPENAI_COMPATIBLE_MODEL: 模型名称（默认 gpt-3.5-turbo）

from __future__ import annotations

import os

from core.provider import Provider, ProviderMetadata
from core.bridge import APIBridge


OPENAI_COMPATIBLE_API_KEY = os.environ.get("OPENAI_COMPATIBLE_API_KEY", "")
OPENAI_COMPATIBLE_BASE_URL = os.environ.get(
    "OPENAI_COMPATIBLE_BASE_URL", "https://api.openai.com/v1"
).rstrip("/")
OPENAI_COMPATIBLE_MODEL = os.environ.get("OPENAI_COMPATIBLE_MODEL", "gpt-3.5-turbo")


class OpenAICompatibleProvider(Provider):
    """OpenAI 兼容 API Provider，使用 APIBridge。

    支持任何实现 OpenAI Chat Completions API 规范的服务。

    环境变量：
        OPENAI_COMPATIBLE_API_KEY: API 密钥
        OPENAI_COMPATIBLE_BASE_URL: API 基础 URL
        OPENAI_COMPATIBLE_MODEL: 默认模型名称
    """

    metadata = ProviderMetadata(
        name="openai_compatible",
        display_name="OpenAI Compatible",
        description="OpenAI 兼容 API（支持任何 /v1/chat/completions 端点）",
        version="0.1.0",
        capabilities=[
            "code.generate",
            "text.generate",
            "text.summarize",
            "text.translate",
            "general.chat",
        ],
        priority=40,
        fallback=["demo"],
        quota_type="unknown",
        quota_total=-1,
        cost_currency="USD",
        cost_amount=0.01,
        cost_unit="per_call",
    )

    bridge = APIBridge(
        endpoint=f"{OPENAI_COMPATIBLE_BASE_URL}/chat/completions",
        api_key_env="OPENAI_COMPATIBLE_API_KEY",
        method="POST",
        timeout=300,
        body_template={
            "model": OPENAI_COMPATIBLE_MODEL,
            "messages": [
                {"role": "user", "content": "{task}"}
            ],
            "temperature": 0.7,
        },
        response_extractor="choices[0].message.content",
        health_endpoint="/models",
    )

    def health(self) -> bool:
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        return bool(OPENAI_COMPATIBLE_API_KEY)

    def quota_left(self) -> int:
        return -1 if self.authenticated() else 0
