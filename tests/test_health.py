# AI Hub — Health Framework 测试
# V0.6: HealthReport / HealthChecker / HealthRegistry

from __future__ import annotations

import time

import pytest

from core.health import HealthReport, HealthChecker, TTL_DEFAULTS
from core.health_registry import HealthRegistry
from core.provider import Provider, ProviderMetadata
from core.bridge import Bridge


# ── 测试用 Provider ──

class FakeBridge(Bridge):
    def run(self, task):
        from core.bridge import BridgeResult
        return BridgeResult(success=True, output="test")

    def check_available(self):
        return True


class HealthyProvider(Provider):
    """实现了 health() → HealthReport 的 Provider。"""
    metadata = ProviderMetadata(
        name="healthy_p",
        display_name="Healthy Provider",
        description="Test",
        health_type="cli",
    )
    bridge = FakeBridge()

    def health(self):
        return HealthReport.healthy("healthy_p", latency_ms=5,
                                    authenticated=True, quota_ok=True)

    def authenticated(self):
        return True

    def quota_left(self):
        return -1


class UnhealthyProvider(Provider):
    """health() 返回 unavailable。"""
    metadata = ProviderMetadata(
        name="unhealthy_p",
        display_name="Unhealthy Provider",
        description="Test",
        health_type="api",
    )
    bridge = FakeBridge()

    def health(self):
        return HealthReport.unavailable("unhealthy_p", message="Service down")

    def authenticated(self):
        return False

    def quota_left(self):
        return 0


class DegradedProvider(Provider):
    """health() 返回 degraded。"""
    metadata = ProviderMetadata(
        name="degraded_p",
        display_name="Degraded Provider",
        description="Test",
    )
    bridge = FakeBridge()

    def health(self):
        return HealthReport(
            provider="degraded_p",
            status="degraded",
            authenticated=True,
            quota_ok=False,
            latency_ms=5000,
            message="High latency, quota low",
        )

    def authenticated(self):
        return True

    def quota_left(self):
        return 5


class BoolHealthProvider(Provider):
    """老版 health() → bool 的 Provider（兼容性测试）。"""
    metadata = ProviderMetadata(
        name="bool_p",
        display_name="Bool Provider",
        description="Test",
    )
    bridge = FakeBridge()

    def health(self):
        return True

    def authenticated(self):
        return True

    def quota_left(self):
        return -1


class NoHealthProvider(Provider):
    """未实现 health() 的 Provider（基类默认）。"""
    metadata = ProviderMetadata(
        name="nohealth_p",
        display_name="No Health Provider",
        description="Test",
    )
    bridge = FakeBridge()

    def health(self):
        return super().health()

    def authenticated(self):
        return True

    def quota_left(self):
        return -1


class RaisingHealthProvider(Provider):
    """health() 抛异常的 Provider。"""
    metadata = ProviderMetadata(
        name="raise_p",
        display_name="Raising Provider",
        description="Test",
    )
    bridge = FakeBridge()

    def health(self):
        raise RuntimeError("Connection refused")

    def authenticated(self):
        return True

    def quota_left(self):
        return -1


# ── 测试 HealthReport ──

class TestHealthReport:
    """HealthReport 数据结构测试。"""

    def test_healthy_status(self):
        r = HealthReport.healthy("test", latency_ms=42)
        assert r.status == "healthy"
        assert r.is_healthy
        assert not r.is_unavailable
        assert r.authenticated is True
        assert r.latency_ms == 42

    def test_unavailable_status(self):
        r = HealthReport.unavailable("test", message="down")
        assert r.status == "unavailable"
        assert r.is_unavailable
        assert not r.is_healthy
        assert r.authenticated is False

    def test_unknown_default(self):
        r = HealthReport(provider="test")
        assert r.status == "unknown"
        assert r.is_unknown

    def test_unknown_factory(self):
        r = HealthReport.unknown("test")
        assert r.status == "unknown"
        assert "does not implement" in r.message

    def test_degraded_status(self):
        r = HealthReport(provider="test", status="degraded",
                         authenticated=True, quota_ok=False,
                         latency_ms=5000, message="Slow")
        assert r.is_degraded
        assert not r.is_healthy
        assert not r.is_unavailable

    def test_expiry_check(self):
        # 新鲜缓存不过期
        r = HealthReport(provider="test", ttl_seconds=300)
        assert not r.is_expired()

        # 过期缓存
        import datetime
        old = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
        r = HealthReport(provider="test", checked_at=old, ttl_seconds=1)
        assert r.is_expired()

    def test_to_dict(self):
        r = HealthReport.healthy("test", latency_ms=10)
        d = r.to_dict()
        assert d["provider"] == "test"
        assert d["status"] == "healthy"
        assert d["latency_ms"] == 10
        assert "checked_at" in d
        assert "ttl_seconds" in d


# ── 测试 HealthChecker ──

class TestHealthChecker:
    """HealthChecker 测试。"""

    def setup_method(self):
        self.checker = HealthChecker()

    def test_check_healthy_provider(self):
        p = HealthyProvider()
        r = self.checker.check(p)
        assert r.status == "healthy"
        assert r.provider == "healthy_p"
        assert r.authenticated is True

    def test_check_unhealthy_provider(self):
        p = UnhealthyProvider()
        r = self.checker.check(p)
        assert r.status == "unavailable"
        assert "Service down" in r.message

    def test_check_degraded_provider(self):
        p = DegradedProvider()
        r = self.checker.check(p)
        assert r.status == "degraded"
        assert r.quota_ok is False
        assert r.latency_ms == 5000

    def test_check_bool_health_provider(self):
        """老版 health() → bool 升级为 HealthReport。"""
        p = BoolHealthProvider()
        r = self.checker.check(p)
        assert r.status == "healthy"
        assert "bool upgrade" in r.message

    def test_check_no_health_provider(self):
        """未真正实现 health() 的 Provider 返回 unknown。"""
        p = NoHealthProvider()
        r = self.checker.check(p)
        assert r.status == "unknown"

    def test_check_raising_provider(self):
        """health() 抛异常时返回 unavailable。"""
        p = RaisingHealthProvider()
        r = self.checker.check(p)
        assert r.status == "unavailable"
        assert "Connection refused" in r.message

    def test_check_all(self):
        providers = [HealthyProvider(), UnhealthyProvider(), DegradedProvider()]
        results = self.checker.check_all(providers)
        assert results["healthy_p"].status == "healthy"
        assert results["unhealthy_p"].status == "unavailable"
        assert results["degraded_p"].status == "degraded"


# ── 测试 HealthRegistry ──

class TestHealthRegistry:
    """HealthRegistry 缓存测试。"""

    def setup_method(self):
        self.registry = HealthRegistry()
        self.healthy = HealthyProvider()
        self.unhealthy = UnhealthyProvider()

    def test_get_healthy(self):
        r = self.registry.get(self.healthy)
        assert r.status == "healthy"

    def test_get_unhealthy(self):
        r = self.registry.get(self.unhealthy)
        assert r.status == "unavailable"

    def test_cache_hit(self):
        """同一 Provider 第二次 get 应该命中缓存。"""
        r1 = self.registry.get(self.healthy)
        r2 = self.registry.get(self.healthy)
        assert r1 is r2  # 同一个对象（缓存命中）

    def test_force_refresh(self):
        """refresh() 应该强制重新检查。"""
        r1 = self.registry.get(self.healthy)
        r2 = self.registry.refresh(self.healthy)
        assert r1 is not r2  # 不同对象（重新检查了）

    def test_invalidate(self):
        """invalidate() 后应重新检查。"""
        self.registry.get(self.healthy)
        self.registry.invalidate("healthy_p")
        assert not self.registry.is_cached("healthy_p")

    def test_invalidate_all(self):
        self.registry.get(self.healthy)
        self.registry.get(self.unhealthy)
        self.registry.invalidate_all()
        assert not self.registry.is_cached("healthy_p")
        assert not self.registry.is_cached("unhealthy_p")

    def test_get_all(self):
        providers = [self.healthy, self.unhealthy]
        results = self.registry.get_all(providers, lazy=False)
        assert results["healthy_p"].status == "healthy"
        assert results["unhealthy_p"].status == "unavailable"

    def test_get_all_lazy(self):
        providers = [self.healthy, self.unhealthy]
        results = self.registry.get_all(providers, lazy=True)
        assert results["healthy_p"].status == "healthy"
        assert results["unhealthy_p"].status == "unavailable"

    def test_summary(self):
        providers = [self.healthy, self.unhealthy, DegradedProvider()]
        s = self.registry.summary(providers)
        assert s["healthy"] == 1
        assert s["unavailable"] == 1
        assert s["degraded"] == 1
        assert s["total"] == 3
        assert "healthy_p" in s["reports"]
        assert s["reports"]["healthy_p"]["status"] == "healthy"

    def test_ttl_from_metadata_health_type(self):
        """health_type 显式声明时，TTL 应优先使用。"""
        # healthy_p 有 health_type="cli" → TTL=300
        r = self.registry.get(self.healthy)
        assert r.ttl_seconds == 300


# ── 测试完整的 status 流程 ──

class TestStatusIntegration:
    """集成测试：HealthRegistry → ai-hub status 输出格式。"""

    def test_status_output_format(self):
        """模拟 ai-hub status 命令的输出结构。"""
        registry = HealthRegistry()
        providers = [
            HealthyProvider(),
            DegradedProvider(),
            UnhealthyProvider(),
            NoHealthProvider(),
            BoolHealthProvider(),
        ]
        reports = registry.get_all(providers, lazy=False)

        # 模拟 status 输出结构
        lines = []
        lines.append("━━━━━━━━ Providers ━━━━━━━━")
        lines.append(f"{'NAME':<14} {'STATUS':<12} {'AUTH':<6} {'QUOTA':<6}")
        lines.append("-" * 40)

        status_icons = {
            "healthy": "✓ healthy",
            "degraded": "⚡ degraded",
            "unknown": "? unknown",
            "unavailable": "✗ unavailable",
        }

        for p in providers:
            r = reports[p.name]
            icon = status_icons.get(r.status, r.status)
            auth = "✓" if r.authenticated else "✗" if r.authenticated is False else "?"
            quota = "✓" if r.quota_ok else "✗" if r.quota_ok is False else "?"
            lines.append(f"{p.name:<14} {icon:<12} {auth:<6} {quota:<6}")

        output = "\n".join(lines)
        assert "healthy_p" in output
        assert "degraded_p" in output
        assert "unhealthy_p" in output
        assert "nohealth_p" in output
        assert "? unknown" in output
        assert "✓ healthy" in output
        assert "✗ unavailable" in output
        assert "⚡ degraded" in output

    def test_json_output_format(self):
        """模拟 ai-hub status --json 输出。"""
        import json
        registry = HealthRegistry()
        providers = [HealthyProvider(), UnhealthyProvider()]
        reports = registry.get_all(providers, lazy=False)

        json_output = {
            "providers": {k: v.to_dict() for k, v in reports.items()},
            "bridges": {"cli": "✓", "api": "✓", "browser": "✓"},
            "timestamp": reports["healthy_p"].checked_at.isoformat() if "healthy_p" in reports else "",
        }
        assert "providers" in json_output
        assert "healthy_p" in json_output["providers"]
        assert json_output["providers"]["healthy_p"]["status"] == "healthy"


# ── TTL 默认值测试 ──

class TestTTLDefaults:
    """TTL 默认值测试。"""

    def test_cli_ttl(self):
        assert TTL_DEFAULTS["cli"] == 300

    def test_api_ttl(self):
        assert TTL_DEFAULTS["api"] == 120

    def test_browser_ttl(self):
        assert TTL_DEFAULTS["browser"] == 60

    def test_mcp_ttl(self):
        assert TTL_DEFAULTS["mcp"] == 60

    def test_default_ttl(self):
        assert TTL_DEFAULTS["default"] == 120
