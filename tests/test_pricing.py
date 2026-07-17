# tests/test_pricing.py
# V0.9.6 — PricingProvider + StaticPricing 测试（ADR-0019）
#
# 覆盖：
# - 已知 model 的 cost 计算（gpt-4 / gpt-4o / gpt-4o-mini / gpt-3.5-turbo / gpt-4-turbo）
# - 未知 model 走 _default 价格
# - token=0 时 cost=0.0
# - compute 返回 float
# - get_default_pricing 返回 StaticPricing 实例
# - PricingProvider 是抽象基类（不能直接实例化）

import pytest
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from planner.metrics.pricing import (
    PricingProvider,
    StaticPricing,
    get_default_pricing,
    _PRICING_TABLE,
)


class TestStaticPricing:
    """StaticPricing 计价测试。"""

    def test_known_model_gpt4(self):
        """gpt-4: 0.03/1K in + 0.06/1K out。"""
        p = StaticPricing()
        # 1000 in + 500 out → 0.03 + 0.03 = 0.06
        cost = p.compute("gpt-4", token_in=1000, token_out=500)
        assert cost == pytest.approx(0.06, abs=1e-6)
        assert isinstance(cost, float)

    def test_known_model_gpt4o(self):
        """gpt-4o: 0.0025/1K in + 0.01/1K out。"""
        p = StaticPricing()
        # 1000 in + 500 out → 0.0025 + 0.005 = 0.0075
        cost = p.compute("gpt-4o", token_in=1000, token_out=500)
        assert cost == pytest.approx(0.0075, abs=1e-6)

    def test_known_model_gpt4o_mini(self):
        """gpt-4o-mini: 0.00015/1K in + 0.0006/1K out。"""
        p = StaticPricing()
        # 10000 in + 1000 out → 0.0015 + 0.0006 = 0.0021
        cost = p.compute("gpt-4o-mini", token_in=10000, token_out=1000)
        assert cost == pytest.approx(0.0021, abs=1e-6)

    def test_known_model_gpt4_turbo(self):
        """gpt-4-turbo: 0.01/1K in + 0.03/1K out。"""
        p = StaticPricing()
        cost = p.compute("gpt-4-turbo", token_in=2000, token_out=1000)
        # 2 * 0.01 + 1 * 0.03 = 0.05
        assert cost == pytest.approx(0.05, abs=1e-6)

    def test_known_model_gpt35_turbo(self):
        """gpt-3.5-turbo: 0.0005/1K in + 0.0015/1K out。"""
        p = StaticPricing()
        cost = p.compute("gpt-3.5-turbo", token_in=1000, token_out=1000)
        # 0.0005 + 0.0015 = 0.002
        assert cost == pytest.approx(0.002, abs=1e-6)

    def test_unknown_model_uses_default(self):
        """未知 model 走 _default 价格 (0.01, 0.03)。"""
        p = StaticPricing()
        cost = p.compute("some-future-model", token_in=1000, token_out=1000)
        # 0.01 + 0.03 = 0.04
        assert cost == pytest.approx(0.04, abs=1e-6)

    def test_unknown_model_same_as_default(self):
        """未知 model 与显式 _default 价格一致。"""
        p = StaticPricing()
        unknown = p.compute("non-existent-xyz", token_in=1500, token_out=700)
        default_prices = _PRICING_TABLE["_default"]
        expected = round(
            1500 / 1000 * default_prices[0] + 700 / 1000 * default_prices[1], 6
        )
        assert unknown == pytest.approx(expected, abs=1e-9)

    def test_zero_tokens_cost_zero(self):
        """token_in=token_out=0 时 cost=0.0。"""
        p = StaticPricing()
        cost = p.compute("gpt-4", token_in=0, token_out=0)
        assert cost == 0.0

    def test_zero_tokens_unknown_model_cost_zero(self):
        """未知 model + 0 token 也是 0.0。"""
        p = StaticPricing()
        cost = p.compute("anything", token_in=0, token_out=0)
        assert cost == 0.0

    def test_compute_returns_float(self):
        """compute() 始终返回 float。"""
        p = StaticPricing()
        cost = p.compute("gpt-4o", token_in=100, token_out=50)
        assert isinstance(cost, float)

    def test_only_input_tokens(self):
        """只算输入 token。"""
        p = StaticPricing()
        # gpt-4: 1000 in + 0 out → 0.03
        cost = p.compute("gpt-4", token_in=1000, token_out=0)
        assert cost == pytest.approx(0.03, abs=1e-6)

    def test_only_output_tokens(self):
        """只算输出 token。"""
        p = StaticPricing()
        # gpt-4: 0 in + 1000 out → 0.06
        cost = p.compute("gpt-4", token_in=0, token_out=1000)
        assert cost == pytest.approx(0.06, abs=1e-6)

    def test_result_rounded_to_6_decimals(self):
        """cost 保留 6 位小数。"""
        p = StaticPricing()
        # gpt-4o-mini: 1 in + 1 out → 0.00000015 + 0.0000006 = 7.5e-7
        # round(7.5e-7, 6) = 0.0 (因为 7.5e-7 < 1e-6)
        cost = p.compute("gpt-4o-mini", token_in=1, token_out=1)
        # 6 位小数四舍五入
        assert cost == round(1 / 1000 * 0.00015 + 1 / 1000 * 0.0006, 6)


class TestPricingProviderInterface:
    """PricingProvider 接口测试。"""

    def test_pricing_provider_is_abstract(self):
        """PricingProvider 是抽象基类，不能直接实例化。"""
        with pytest.raises(TypeError):
            PricingProvider()  # type: ignore[abstract]

    def test_subclass_must_implement_compute(self):
        """子类必须实现 compute()，否则 TypeError。"""

        class IncompletePricing(PricingProvider):
            pass

        with pytest.raises(TypeError):
            IncompletePricing()  # type: ignore[abstract]

    def test_custom_subclass_works(self):
        """自定义子类实现 compute() 可正常使用。"""

        class FixedPricing(PricingProvider):
            def compute(self, model: str, token_in: int, token_out: int) -> float:
                return 0.42

        p = FixedPricing()
        assert p.compute("any", 100, 100) == 0.42


class TestGetDefaultPricing:
    """get_default_pricing() 单例测试。"""

    def test_returns_static_pricing_instance(self):
        """get_default_pricing() 返回 StaticPricing 实例。"""
        p = get_default_pricing()
        assert isinstance(p, StaticPricing)

    def test_returns_pricing_provider(self):
        """返回的对象是 PricingProvider。"""
        p = get_default_pricing()
        assert isinstance(p, PricingProvider)

    def test_singleton_identity(self):
        """两次调用返回同一实例（进程级单例）。"""
        p1 = get_default_pricing()
        p2 = get_default_pricing()
        assert p1 is p2

    def test_default_pricing_can_compute(self):
        """默认 pricing 实例可正常 compute()。"""
        p = get_default_pricing()
        cost = p.compute("gpt-4", token_in=1000, token_out=1000)
        # 0.03 + 0.06 = 0.09
        assert cost == pytest.approx(0.09, abs=1e-6)
