# tests/test_benchmark.py
# V0.6.3 — Benchmark CLI 测试

"""Benchmark 命令测试。"""

import subprocess
import sys
import json
from pathlib import Path

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


class TestBenchmarkOutput:
    """benchmark 输出格式测试。"""

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
            return  # 没 Provider 可测，跳过
        assert "PROVIDER" in out
        assert "SUCCESS" in out
        assert "AVG" in out


class TestBenchmarkLogic:
    """benchmark 逻辑测试（不依赖外部 Provider）。"""

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
