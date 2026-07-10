# AI Hub — OpenAI API Provider（使用 APIBridge）
#
# 演示 APIBridge 的用法。
# 接入任何 HTTP API 类 AI 平台都参考此模板。
#
# 通信方式：HTTP API
# Bridge: APIBridge

from __future__ import annotations

import os
from typing import Any

from core.provider import Provider, ProviderMetadata
from core.bridge import APIBridge
from core.result import Result


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
        fallback=["gemini_cli", "demo"],
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
        # API 通常无免费额度限制概念，返回 -1
        return -1 if self.authenticated() else 0

    def execute(self, task: str, context: dict[str, Any] | None = None) -> Result:
        br = self._run_bridge(
            task,
            extra_body={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": task}],
            },
        )
        result = self._bridge_to_result(br, self.name)
        result.metadata["model"] = "gpt-4o-mini"
        result.metadata["quota_remaining"] = self.quota_left()
        return result
