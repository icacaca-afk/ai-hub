# tests/test_metrics_extractor.py
# V0.9.6 — MetricsExtractor 测试（ADR-0019）
#
# 覆盖：
# - extract openai_api provider（br.raw 为 JSON 字符串含 usage）
# - extract openai_compatible 同上
# - 非 OpenAI provider 返回空 dict
# - br.success=False 返回空 dict
# - br.raw=None 返回空 dict
# - JSON 解析失败容错（br.raw 是无效 JSON 字符串）
# - br.raw 是 dict 类型（非 str）也能处理
# - br.raw 非 dict / 非 str（如 int）返回空 dict
# - 缺失 usage 字段时返回 token=0 + cost=0.0

import json
import pytest
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.bridge import BridgeResult
from planner.metrics.extractors import MetricsExtractor


# ── 测试用 Bridge stub（MetricsExtractor 不直接使用 bridge，但接受参数） ──

class _FakeBridge:
    """测试用 Bridge stub。"""
    pass


# ── OpenAI provider 提取测试 ──

class TestExtractOpenAI:
    """MetricsExtractor.extract() 对 openai_api / openai_compatible 的测试。"""

    def test_extract_openai_api_json_string(self):
        """openai_api: br.raw 为 JSON 字符串含 usage → 提取 token/cost。"""
        raw = json.dumps({
            "model": "gpt-4o",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        })
        br = BridgeResult(success=True, output="ok", raw=raw)
        m = MetricsExtractor.extract("openai_api", _FakeBridge(), br)

        assert m["token_in"] == 100
        assert m["token_out"] == 50
        assert m["token_total"] == 150
        assert m["model"] == "gpt-4o"
        # gpt-4o: 0.0025/1K in + 0.01/1K out
        # 100/1000 * 0.0025 + 50/1000 * 0.01 = 0.00025 + 0.0005 = 0.00075
        assert m["cost_usd"] == pytest.approx(0.00075, abs=1e-9)

    def test_extract_openai_compatible_json_string(self):
        """openai_compatible: 同 openai_api 的提取逻辑。"""
        raw = json.dumps({
            "model": "gpt-4o-mini",
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "total_tokens": 1200,
            },
        })
        br = BridgeResult(success=True, output="ok", raw=raw)
        m = MetricsExtractor.extract("openai_compatible", _FakeBridge(), br)

        assert m["token_in"] == 1000
        assert m["token_out"] == 200
        assert m["token_total"] == 1200
        assert m["model"] == "gpt-4o-mini"

    def test_extract_raw_is_dict(self):
        """br.raw 是已解析的 dict（非字符串）也能处理。"""
        raw = {
            "model": "gpt-4",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
        br = BridgeResult(success=True, output="ok", raw=raw)
        m = MetricsExtractor.extract("openai_api", _FakeBridge(), br)

        assert m["token_in"] == 10
        assert m["token_out"] == 5
        assert m["token_total"] == 15
        assert m["model"] == "gpt-4"

    def test_extract_missing_total_tokens(self):
        """usage 缺 total_tokens → 用 prompt + completion 之和。"""
        raw = json.dumps({
            "model": "gpt-4o",
            "usage": {
                "prompt_tokens": 30,
                "completion_tokens": 20,
                # 没有 total_tokens
            },
        })
        br = BridgeResult(success=True, output="ok", raw=raw)
        m = MetricsExtractor.extract("openai_api", _FakeBridge(), br)

        assert m["token_in"] == 30
        assert m["token_out"] == 20
        assert m["token_total"] == 50  # 30 + 20

    def test_extract_missing_usage(self):
        """缺失 usage 字段 → token_in/out/total=0, cost=0.0。"""
        raw = json.dumps({"model": "gpt-4o"})
        br = BridgeResult(success=True, output="ok", raw=raw)
        m = MetricsExtractor.extract("openai_api", _FakeBridge(), br)

        assert m["token_in"] == 0
        assert m["token_out"] == 0
        assert m["token_total"] == 0
        assert m["cost_usd"] == 0.0
        assert m["model"] == "gpt-4o"

    def test_extract_unknown_model(self):
        """未知 model 走 _default 价格。"""
        raw = json.dumps({
            "model": "claude-opus-4",
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 1000,
                "total_tokens": 2000,
            },
        })
        br = BridgeResult(success=True, output="ok", raw=raw)
        m = MetricsExtractor.extract("openai_api", _FakeBridge(), br)

        # _default: 0.01/1K in + 0.03/1K out
        # 1000/1000 * 0.01 + 1000/1000 * 0.03 = 0.04
        assert m["cost_usd"] == pytest.approx(0.04, abs=1e-9)
        assert m["model"] == "claude-opus-4"

    def test_extract_returns_dict_with_expected_keys(self):
        """返回的 dict 含 5 个固定 key。"""
        raw = json.dumps({
            "model": "gpt-4",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })
        br = BridgeResult(success=True, output="ok", raw=raw)
        m = MetricsExtractor.extract("openai_api", _FakeBridge(), br)

        assert set(m.keys()) == {
            "token_in", "token_out", "token_total", "cost_usd", "model"
        }


# ── 容错测试 ──

class TestExtractFailures:
    """MetricsExtractor 容错测试。"""

    def test_failed_bridge_result_returns_empty(self):
        """br.success=False → 返回空 dict。"""
        raw = json.dumps({"model": "gpt-4", "usage": {"prompt_tokens": 100}})
        br = BridgeResult(success=False, output="", error="boom", raw=raw)
        m = MetricsExtractor.extract("openai_api", _FakeBridge(), br)
        assert m == {}

    def test_none_raw_returns_empty(self):
        """br.raw=None → 返回空 dict。"""
        br = BridgeResult(success=True, output="ok", raw=None)
        m = MetricsExtractor.extract("openai_api", _FakeBridge(), br)
        assert m == {}

    def test_invalid_json_string_returns_empty(self):
        """br.raw 是无效 JSON 字符串 → 容错返回空 dict（不抛异常）。"""
        br = BridgeResult(success=True, output="ok", raw="{not valid json")
        m = MetricsExtractor.extract("openai_api", _FakeBridge(), br)
        assert m == {}

    def test_raw_is_non_dict_non_str_returns_empty(self):
        """br.raw 是 int（非 str/dict）→ _extract_openai 返回 {}。"""
        br = BridgeResult(success=True, output="ok", raw=42)
        m = MetricsExtractor.extract("openai_api", _FakeBridge(), br)
        assert m == {}

    def test_raw_is_list_returns_empty(self):
        """br.raw 是 list（非 dict）→ 返回 {}。"""
        br = BridgeResult(success=True, output="ok", raw=[1, 2, 3])
        m = MetricsExtractor.extract("openai_api", _FakeBridge(), br)
        assert m == {}

    def test_unknown_provider_returns_empty(self):
        """未知 provider name → 默认 handler 返回空 dict。"""
        raw = json.dumps({"model": "gpt-4", "usage": {"prompt_tokens": 100}})
        br = BridgeResult(success=True, output="ok", raw=raw)
        m = MetricsExtractor.extract("some_other_provider", _FakeBridge(), br)
        assert m == {}

    def test_gemini_provider_returns_empty(self):
        """gemini provider（无 handler）→ 返回空 dict。"""
        raw = "some cli stdout"
        br = BridgeResult(success=True, output="ok", raw=raw)
        m = MetricsExtractor.extract("gemini_cli", _FakeBridge(), br)
        assert m == {}

    def test_qoder_provider_returns_empty(self):
        """qoder provider（无 handler）→ 返回空 dict。"""
        br = BridgeResult(success=True, output="ok", raw="anything")
        m = MetricsExtractor.extract("qoder", _FakeBridge(), br)
        assert m == {}


# ── 静态方法 / 接口测试 ──

class TestMetricsExtractorInterface:
    """MetricsExtractor 接口测试。"""

    def test_extract_is_static_method(self):
        """extract 是静态方法，可直接通过类名调用。"""
        br = BridgeResult(success=True, output="ok", raw=None)
        # 不需要实例化
        m = MetricsExtractor.extract("any", _FakeBridge(), br)
        assert m == {}

    def test_extract_never_raises(self):
        """extract 不抛异常（即使参数异常）。"""
        # 传入 None bridge / None br 都应被 try-except 捕获
        # 注：br.success 会 AttributeError，但被 try/except 捕获
        br = BridgeResult(success=True, output="ok", raw=None)
        # raw=None 时直接 return {}，不进入 try
        m = MetricsExtractor.extract("openai_api", None, br)
        assert m == {}
