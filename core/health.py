# AI Hub — Health Framework
# V0.6: Provider 可观测性基础设施
#
# Health 是 Capability，不是 Provider Interface。
# Provider 可以选择性地实现 health() -> HealthReport。
# 未实现 health() 的 Provider 返回 status="unknown"。
#
# 设计原则：
#   - core/provider.py 不动（ADR-0008 Core Freeze）
#   - HealthChecker 通过 callable(getattr()) 发现，不强制所有 Provider 实现
#   - normalize_health_result() 统一处理 bool/HealthReport/Exception 升级
#   - 新增文件：core/health.py + core/health_registry.py
#
# API Stability: Experimental（V0.6 新增）

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class HealthReport:
    """Provider 健康检查结果。

    Attributes:
        provider: Provider 名称标识符
        status: healthy / degraded / unknown / unavailable
        authenticated: 是否已认证（None = 无法检测）
        quota_ok: 额度是否充足（None = 无法检测）
        latency_ms: 检查耗时毫秒（None = 未执行检查）
        message: 人类可读的状态描述
        checked_at: 检查时间
        ttl_seconds: 缓存有效期（秒）
    """

    provider: str
    status: str = "unknown"
    authenticated: Optional[bool] = None
    quota_ok: Optional[bool] = None
    latency_ms: Optional[int] = None
    message: str = ""
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: int = 120

    # ── 状态常量 ──

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"

    # ── 便捷判断 ──

    @property
    def is_healthy(self) -> bool:
        return self.status == self.HEALTHY

    @property
    def is_degraded(self) -> bool:
        return self.status == self.DEGRADED

    @property
    def is_unknown(self) -> bool:
        return self.status == self.UNKNOWN

    @property
    def is_unavailable(self) -> bool:
        return self.status == self.UNAVAILABLE

    def is_expired(self) -> bool:
        """检查缓存是否过期。"""
        elapsed = (datetime.now(timezone.utc) - self.checked_at).total_seconds()
        return elapsed > self.ttl_seconds

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "status": self.status,
            "authenticated": self.authenticated,
            "quota_ok": self.quota_ok,
            "latency_ms": self.latency_ms,
            "message": self.message,
            "checked_at": self.checked_at.isoformat(),
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def unknown(cls, provider_name: str) -> "HealthReport":
        """创建 unknown 状态报告（未实现 health() 的 Provider）。"""
        return cls(
            provider=provider_name,
            status=cls.UNKNOWN,
            message="Provider does not implement health()",
        )

    @classmethod
    def healthy(cls, provider_name: str, latency_ms: int = 0,
                authenticated: bool = True, quota_ok: Optional[bool] = None,
                message: str = "") -> "HealthReport":
        """创建 healthy 状态报告。"""
        return cls(
            provider=provider_name,
            status=cls.HEALTHY,
            authenticated=authenticated,
            quota_ok=quota_ok,
            latency_ms=latency_ms,
            message=message or "OK",
        )

    @classmethod
    def unavailable(cls, provider_name: str, message: str = "",
                    latency_ms: int = 0) -> "HealthReport":
        """创建 unavailable 状态报告。"""
        return cls(
            provider=provider_name,
            status=cls.UNAVAILABLE,
            authenticated=False,
            quota_ok=False,
            latency_ms=latency_ms,
            message=message or "Provider is not available",
        )

    def __repr__(self) -> str:
        return (f"<HealthReport provider={self.provider!r} "
                f"status={self.status!r} auth={self.authenticated}>")


# ── TTL 默认值（按 health_type 分） ──

TTL_DEFAULTS = {
    "cli": 300,       # CLI Provider: 5 minutes
    "api": 120,       # API Provider: 2 minutes
    "browser": 60,    # Browser Provider: 1 minute
    "mcp": 60,        # MCP: 1 minute
    "default": 120,   # 默认 2 minutes
}


class HealthChecker:
    """Provider 健康检查器。

    通过 Optional Protocol 检测 Provider 是否实现了 health()。
    未实现的 Provider 返回 status="unknown"（安全默认，不假设可用）。
    不像 available() 那样拍板"可用/不可用"，而是提供细粒度状态信息。

    用法：
        checker = HealthChecker()
        report = checker.check(provider)  # 直接调
        # 或
        report = checker.check("gemini_cli")  # 通过 HealthRegistry
    """

    # ── 核心检查 ──

    def check(self, provider: "Provider | object") -> HealthReport:
        """对某个 Provider 执行健康检查。

        流程：
        1. 检测 health() 是否被子类覆盖（Optional Protocol）
        2. 调用 health() 获取原始结果
        3. 通过 normalize_health_result() 统一升级

        Args:
            provider: Provider 实例

        Returns:
            HealthReport
        """
        name = getattr(provider, "name", "unknown")

        import time
        start = time.time()

        try:
            # ① Optional Protocol 检测：用 callable(getattr()) 替代 hasattr + 方法比较
            if not self._has_health_implementation(provider):
                return HealthReport.unknown(name)

            # ② 调用 health()
            result = provider.health()
            elapsed_ms = int((time.time() - start) * 1000)

            # ③ 统一升级
            return self._normalize_health_result(name, result, elapsed_ms)

        except Exception as e:
            elapsed_ms = int((time.time() - start) * 1000)
            return HealthReport.unavailable(
                name,
                message=f"health() raised: {e}",
                latency_ms=elapsed_ms,
            )

    # ── 批量检查 ──

    def check_all(self, providers: list) -> dict[str, HealthReport]:
        """批量检查多个 Provider。

        Returns:
            {provider_name: HealthReport} 字典
        """
        return {p.name: self.check(p) for p in providers}

    # ── 内部方法 ──

    def _has_health_implementation(self, provider) -> bool:
        """检测 Provider 是否真正实现了 health()（Optional Protocol）。

        两层判断：
        1. callable(getattr(...)) — 安全检测（回避 property 副作用）
        2. 子类方法 ≠ 基类默认 — 区分「覆盖了」和「继承了抽象方法」
        """
        health_fn = getattr(provider, "health", None)
        if not callable(health_fn):
            return False

        # 检查子类是否真正覆盖了 health()
        from core.provider import Provider as _Provider
        if isinstance(provider, _Provider):
            provider_health = type(provider).health
            base_provider_health = _Provider.health
            if provider_health is base_provider_health:
                return False

        return True

    def _normalize_health_result(
        self, provider_name: str, result, elapsed_ms: int
    ) -> HealthReport:
        """统一升级：将 health() 的返回值标准化为 HealthReport。

        支持的返回类型：
        - HealthReport → 直接返回（保护 Provider 自己的 latency_ms）
        - bool → 升级：True=healthy, False=unavailable
        - 其他 → unknown
        """
        if isinstance(result, HealthReport):
            # 保护 Provider 自己计时的精度
            if result.latency_ms is None:
                result.latency_ms = elapsed_ms
            return result

        if isinstance(result, bool):
            if result:
                return HealthReport.healthy(
                    provider_name,
                    latency_ms=elapsed_ms,
                    message="OK (bool upgrade)",
                )
            else:
                return HealthReport.unavailable(
                    provider_name,
                    message="health() returned False",
                    latency_ms=elapsed_ms,
                )

        return HealthReport(
            provider=provider_name,
            status=HealthReport.UNKNOWN,
            latency_ms=elapsed_ms,
            message=f"Unexpected health() return type: {type(result).__name__}",
        )
