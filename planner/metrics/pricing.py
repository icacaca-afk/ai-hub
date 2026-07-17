# AI Hub — Pricing Provider
# V0.9.6: Provider token/cost 估算（ADR-0019）
#
# 接口化 Pricing：默认 StaticPricing 用静态 dict 计价。
# 未来可替换为动态拉取 / DB / 远端配置等实现（同接口）。
#
# 单位：cost_usd 为 USD，price 单位 = USD / 1K tokens（与 OpenAI 官网计价一致）。
#
# API Stability: Experimental

from __future__ import annotations

from abc import ABC, abstractmethod


class PricingProvider(ABC):
    """Pricing 来源接口。默认 StaticPricing 用静态 dict。

    实现方只需实现 compute() + is_known()。

    API Stability: Experimental
    """

    @abstractmethod
    def compute(self, model: str, token_in: int, token_out: int) -> float:
        """根据 model + 输入/输出 token 数估算 USD 成本。

        未知 model 返回 0.0（不猜测价格）。

        Args:
            model: 模型名（如 "gpt-4o"）
            token_in: 输入 token 数
            token_out: 输出 token 数

        Returns:
            USD 成本（float，保留 6 位小数）；未知 model 返回 0.0
        """
        ...

    @abstractmethod
    def is_known(self, model: str) -> bool:
        """该 model 是否有价格信息（用于 estimated 标记）。"""
        ...


# 静态计价表（USD / 1K tokens），(input_price, output_price)
_PRICING_TABLE: dict[str, tuple[float, float]] = {
    "gpt-4":           (0.03, 0.06),
    "gpt-4-turbo":     (0.01, 0.03),
    "gpt-4o":          (0.0025, 0.01),
    "gpt-4o-mini":     (0.00015, 0.0006),
    "gpt-3.5-turbo":   (0.0005, 0.0015),
}


class StaticPricing(PricingProvider):
    """静态 dict 计价实现。

    未知 model 返回 0.0（ChatGPT Q5 建议：不猜测价格）。
    已知 model 按 token 数估算 USD 成本。

    API Stability: Experimental
    """

    def compute(self, model: str, token_in: int, token_out: int) -> float:
        prices = _PRICING_TABLE.get(model)
        if prices is None:
            # 未知 model：不估算，返回 0（避免误导用户）
            return 0.0
        return round(
            token_in / 1000 * prices[0] + token_out / 1000 * prices[1],
            6,
        )

    def is_known(self, model: str) -> bool:
        """该 model 是否在价格表中。"""
        return model in _PRICING_TABLE


_default_pricing = StaticPricing()


def get_default_pricing() -> PricingProvider:
    """返回进程级默认 PricingProvider 单例。"""
    return _default_pricing
