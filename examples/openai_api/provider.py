"""Example: OpenAI API Provider (minimal, OpenAI-compatible).

Copy this file, change 3 things:
  1. metadata.name + capabilities
  2. endpoint + api_key_env + model
  3. health/authenticated/quota_left
"""
import os
from core.provider import Provider, ProviderMetadata
from core.bridge import APIBridge, BridgeResult
from core.task import Task
import json, time, urllib.request, urllib.error


class OpenAICompatBridge(APIBridge):
    """Subclass APIBridge, override run() for OpenAI chat format."""
    def __init__(self, endpoint, api_key_env, model="gpt-4o-mini", timeout=60):
        super().__init__(endpoint=endpoint, api_key_env=api_key_env, method="POST", timeout=timeout)
        self.model = model

    def run(self, task: Task, **kwargs) -> BridgeResult:
        key = self._get_api_key()
        if not key:
            return BridgeResult(success=False, output="", error=f"No key: {self.api_key_env}")
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": task.content}]}).encode()
        req = urllib.request.Request(self.endpoint, data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {key}"
        }, method="POST")
        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode())
                return BridgeResult(success=True, output=data["choices"][0]["message"]["content"],
                                    duration_ms=int((time.time()-start)*1000), raw=data)
        except urllib.error.HTTPError as e:
            return BridgeResult(success=False, output="", error=f"HTTP {e.code}: {e.read().decode()[:200]}",
                                duration_ms=int((time.time()-start)*1000))
        except Exception as e:
            return BridgeResult(success=False, output="", error=str(e),
                                duration_ms=int((time.time()-start)*1000))


class OpenAIAPIProvider(Provider):
    metadata = ProviderMetadata(
        name="openai_api",
        display_name="OpenAI API",
        description="OpenAI 兼容 API (DeepSeek / OpenAI)",
        version="0.0.2",
        capabilities=["code.generate", "text.generate", "text.summarize", "text.translate", "general.chat"],
        priority=50,
        fallback=["demo"],
        quota_type="unknown", quota_total=-1,
    )

    bridge = OpenAICompatBridge(
        endpoint="https://api.deepseek.com/v1/chat/completions",
        api_key_env="DEEPSEEK_API_KEY",
        model="deepseek-chat",
    )

    def health(self): return self.bridge.check_available()
    def authenticated(self): return self.bridge.check_auth()
    def quota_left(self): return -1 if self.authenticated() else 0
