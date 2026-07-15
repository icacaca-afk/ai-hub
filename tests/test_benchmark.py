# tests/test_benchmark.py
# V0.6.3 — Benchmark CLI 测试
# V0.8.2 — 拆分为单元测试 + live 测试（FakeProvider 隔离）

"""Benchmark 命令测试。

单元测试：使用 FakeProvider + 模拟延迟，不依赖外部 Provider。
Live 测试：标记 @pytest.mark.live，CI 默认跳过。
"""

import subprocess
import sys
import json
from pathlib import Path

import pytest

# 确保 ai-hub 在 path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _run_benchmark(args=None):
    """运行 ai-hub benchmark 子进程。"""
    cmd = [sys.executable, "-m", "cli.main", "benchmark"]
    if args:
        cmd.extend(args)
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT),
                       timeout=60, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout, r.stderr


class TestBenchmarkUnit:
    """单元测试：FakeProvider 隔离，验证 benchmark 逻辑。"""

    def test_benchmark_skip_unhealthy(self):
        """不健康的 Provider 不参与 benchmark。"""
        from core.health import HealthReport
        from core.health_registry import HealthRegistry
        from core.provider import Provider, ProviderMetadata
        from core.bridge import FakeBridge

        class FakeHealthyProvider(Provider):
            metadata = ProviderMetadata(
                name="fake_bench", display_name="Fake Bench",
                description="test", health_type="api",
            )
            bridge = FakeBridge()

            def health(self):
                return HealthReport.healthy("fake_bench")

            def authenticated(self):
                return True

            def quota_left(self):
                return -1

        # 验证 HealthRegistry 能正确识别
        hr = HealthRegistry()
        report = hr.get(FakeHealthyProvider())
        assert report.is_healthy

    def test_benchmark_logic_with_fake_provider(self):
        """用 FakeProvider 验证 benchmark 评分逻辑。"""
        from core.health import HealthReport
        from core.bridge import Bridge, BridgeResult
        from core.provider import Provider, ProviderMetadata
        from core.task import Task

        class FakeBenchProvider(Provider):
            """模拟 Provider，返回固定结果和延迟。"""
            metadata = ProviderMetadata(
                name="fake_bench_unit",
                display_name="Fake Bench Unit",
                description="test provider for benchmark",
                capabilities=["code.generate"],
                priority=50,
                health_type="api",
            )

            def __init__(self):
                self.bridge = type("FakeBenchBridge", (), {
                    "run": lambda self, task: BridgeResult(
                        success=True,
                        output="OK",
                    )
                })()

            def health(self):
                return HealthReport.healthy("fake_bench_unit", latency_ms=100)

            def authenticated(self):
                return True

            def quota_left(self):
                return -1

        p = FakeBenchProvider()
        task = Task.from_text("Reply with exactly: OK")
        bridge = p.select_bridge(task)
        result = bridge.run(task)

        assert result.success
        assert result.output == "OK"

    def test_latency_score_calculation(self):
        """验证 latency score 线性插值逻辑。"""
        from router.score_router import ScoreRouter
        from core.health import HealthReport
        from core.provider import Provider, ProviderMetadata
        from core.bridge import FakeBridge
        from core.registry import CapabilityRegistry
        from core.health_registry import HealthRegistry

        class TestP(Provider):
            metadata = ProviderMetadata(
                name="test_lat", display_name="Test Latency",
                description="test", capabilities=["code.generate"],
                priority=50, health_type="api",
            )
            bridge = FakeBridge()

            def health(self):
                return HealthReport.healthy("test_lat")

            def authenticated(self):
                return True

            def quota_left(self):
                return -1

        registry = CapabilityRegistry()
        registry.register(TestP())
        router = ScoreRouter(registry, quota_manager=None, health_registry=HealthRegistry())

        p = registry.get("test_lat")

        # latency ≤ 1s → score 100
        report_fast = HealthReport.healthy("test_lat", latency_ms=500)
        s_fast = router._score_provider(p, ["code.generate"], report_fast)
        assert s_fast.latency_score == 100.0

        # latency = 5s → score ~50
        report_mid = HealthReport.healthy("test_lat", latency_ms=5000)
        s_mid = router._score_provider(p, ["code.generate"], report_mid)
        assert 40 < s_mid.latency_score < 60

        # latency ≥ 10s → score 0
        report_slow = HealthReport.healthy("test_lat", latency_ms=10000)
        s_slow = router._score_provider(p, ["code.generate"], report_slow)
        assert s_slow.latency_score == 0.0

        # no latency data → score 50
        s_none = router._score_provider(p, ["code.generate"], None)
        assert s_none.latency_score == 50.0


@pytest.mark.live
class TestBenchmarkLive:
    """Live 测试：需要真实 Provider，CI 默认跳过。

    运行方式：pytest tests/test_benchmark.py -m live
    """

    def test_benchmark_runs(self):
        """benchmark 能正常执行（不崩溃）。"""
        rc, out, err = _run_benchmark()
        assert rc == 0, f"exit={rc} stderr={err}"
        assert "Benchmark" in out or "No healthy" in out

    def test_benchmark_json(self):
        """JSON 输出格式正确。"""
        rc, out, err = _run_benchmark(["--json"])
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        assert "benchmark" in data
        assert isinstance(data["benchmark"], list)

    def test_benchmark_table_header(self):
        """表格输出有正确表头。"""
        rc, out, err = _run_benchmark()
        if "No healthy" in out:
            pytest.skip("No healthy providers available")
        assert "PROVIDER" in out
        assert "SUCCESS" in out
        assert "AVG" in out
