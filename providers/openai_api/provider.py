# AI Hub — OpenAI API Provider（使用 APIBridge）
#
# 通信方式：HTTP API（OpenAI 兼容格式）
# Bridge: APIBridge（core/bridge.py）
#
# 支持 OpenAI 兼容 API：
#   - OpenAI (https://api.openai.com/v1/chat/completions)
#   - DeepSeek (https://api.deepseek.com/v1/chat/completions)
#   - Moonshot (https://api.moonshot.cn/v1/chat/completions)
#   - Qwen (https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions)
#
# 通过环境变量选择后端：
#   OPENAI_API_KEY  → 使用 OpenAI 官方
#   DEEPSEEK_API_KEY → 使用 DeepSeek（自动检测）
#
# ADR: docs/adr/0004-openai-api-integration.md

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from core.provider import Provider, ProviderMetadata
from core.bridge import APIBridge, BridgeResult
from core.task import Task


class OpenAICompatBridge(APIBridge):
    """OpenAI 兼容 API 桥接器。

    继承 APIBridge，重写 run() 以发送 OpenAI Chat Completions 格式。
    不修改 core/bridge.py。

    支持的 body 格式：
    {
        "model": "<model>",
        "messages": [{"role": "user", "content": "<task>"}],
        "max_tokens": <int>,
        "temperature": <float>
    }
    """

    def __init__(
        self,
        endpoint: str,
        api_key_env: str,
        model: str = "gpt-4o-mini",
        timeout: int = 300,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ):
        super().__init__(
            endpoint=endpoint,
            api_key_env=api_key_env,
            method="POST",
            timeout=timeout,
        )
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    def run(self, task: Task, **kwargs) -> BridgeResult:
        api_key = self._get_api_key()
        if not api_key:
            return BridgeResult(
                success=False,
                output="",
                error=f"API key not set in env: {self.api_key_env}",
            )

        body = json.dumps({
            "model": kwargs.get("model", self.model),
            "messages": [
                {"role": "user", "content": task.content}
            ],
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers=headers,
            method="POST",
        )

        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                # 提取 assistant 回复
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})
                duration = int((time.time() - start) * 1000)
                return BridgeResult(
                    success=True,
                    output=content,
                    duration_ms=duration,
                    artifacts=[],
                    raw=data,
                )
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")[:500]
            return BridgeResult(
                success=False,
                output="",
                error=f"HTTP {e.code}: {e.reason} | {error_body}",
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return BridgeResult(
                success=False,
                output="",
                error=str(e),
                duration_ms=int((time.time() - start) * 1000),
            )


def _detect_backend() -> tuple[str, str, str]:
    """自动检测可用的 OpenAI 兼容后端。

    返回: (endpoint, api_key_env, model)
    """
    if os.environ.get("DEEPSEEK_API_KEY"):
        return (
            "https://api.deepseek.com/v1/chat/completions",
            "DEEPSEEK_API_KEY",
            "deepseek-chat",
        )
    if os.environ.get("OPENAI_API_KEY"):
        return (
            "https://api.openai.com/v1/chat/completions",
            "OPENAI_API_KEY",
            "gpt-4o-mini",
        )
    # 默认 OpenAI（会因无 key 而降级）
    return (
        "https://api.openai.com/v1/chat/completions",
        "OPENAI_API_KEY",
        "gpt-4o-mini",
    )


_endpoint, _key_env, _model = _detect_backend()


class OpenAIAPIProvider(Provider):
    """OpenAI 兼容 API Provider。

    自动检测后端：DeepSeek 优先（如果 DEEPSEEK_API_KEY 存在），否则 OpenAI。
    支持 OpenAI 兼容 API 格式的任何后端。
    """

    metadata = ProviderMetadata(
        name="openai_api",
        display_name="OpenAI API",
        description="OpenAI 兼容 API (DeepSeek / OpenAI / Moonshot / Qwen)",
        version="0.0.2",
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

    bridge = OpenAICompatBridge(
        endpoint=_endpoint,
        api_key_env=_key_env,
        model=_model,
        timeout=60,
        max_tokens=4096,
        temperature=0.7,
    )

    def health(self) -> bool:
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        return self.bridge.check_auth()

    def quota_left(self) -> int:
        return -1 if self.authenticated() else 0
