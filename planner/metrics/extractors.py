# AI Hub — Metrics Extractor
# V0.9.6: 从 BridgeResult.raw 提取 server_metrics（ADR-0019）
#
# 按 provider name 分发：每个 provider 有专属 handler，
# 从 br.raw（HTTP body / subprocess stdout）提取 usage/token/cost。
#
# 返回 dict（符合 ADR-0018 原则 B JSON 可序列化）：
#   {
#     "token_in": int,
#     "token_out": int,
#     "token_total": int,
#     "cost_usd": float,
#     "model": str,
#   }
# 失败/无数据返回空 dict {}。
#
# 不抛异常（容错：日志 warn + 返回 {}），不影响主链路。
#
# API Stability: Experimental

from __future__ import annotations

import json
import logging
from typing import Any, Callable

_log = logging.getLogger(__name__)


class MetricsExtractor:
    """按 provider name 分发提取 server_metrics。

    静态方法 extract() 是入口：
        1. br.success=False / br.raw=None → 返回 {}
        2. 查 _HANDLERS[provider_name]，无则 _extract_nothing
        3. 调 handler(bridge, br)，异常被 catch + warn + 返回 {}

    API Stability: Experimental
    """

    @staticmethod
    def extract(provider_name: str, bridge, br) -> dict[str, Any]:
        """提取 server_metrics。

        Args:
            provider_name: Provider 名称（如 "openai_api"）
            bridge: Bridge 实例（保留参数，供 handler 读取 bridge 上下文）
            br: BridgeResult

        Returns:
            dict（含 token_in/token_out/token_total/cost_usd/model）或空 dict
        """
        if not br.success or br.raw is None:
            return {}
        handler: Callable = _HANDLERS.get(provider_name, _extract_nothing)
        try:
            return handler(bridge, br)
        except Exception as exc:
            # ChatGPT Q4 建议：log 带 Exception Type，便于排查
            _log.warning(
                "MetricsExtractor extract failed provider=%s (%s): %s",
                provider_name, type(exc).__name__, exc,
            )
            return {}


def _extract_nothing(bridge, br) -> dict:
    """未知 provider 的默认 handler：返回空 dict。"""
    return {}


def _extract_openai(bridge, br) -> dict:
    """从 OpenAI HTTP response body 提取 usage。

    支持 br.raw 为 JSON 字符串或已解析 dict。
    """
    data = json.loads(br.raw) if isinstance(br.raw, str) else br.raw
    if not isinstance(data, dict):
        return {}
    usage = data.get("usage", {})
    model = data.get("model", "")
    token_in = usage.get("prompt_tokens", 0)
    token_out = usage.get("completion_tokens", 0)
    token_total = usage.get("total_tokens", token_in + token_out)

    # 延迟 import 避免循环依赖
    from planner.metrics.pricing import get_default_pricing
    cost = get_default_pricing().compute(model, token_in, token_out)

    return {
        "token_in": int(token_in),
        "token_out": int(token_out),
        "token_total": int(token_total),
        "cost_usd": cost,
        "model": model,
    }


# provider_name → handler 映射
_HANDLERS: dict[str, Callable] = {
    "openai_api": _extract_openai,
    "openai_compatible": _extract_openai,
}
