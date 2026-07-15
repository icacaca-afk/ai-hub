# tests/test_cli_score_integration.py
# V0.8.2 — CLI ScoreRouter Integration Regression Test
#
# 入口级保护：验证 ai-hub explain-route 经过 ScoreRouter。
# 只测 explain-route（不实际执行 Provider），避免 subprocess 超时。

import subprocess
import sys
import os
import json

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def _run_cli(*args, timeout=30):
    """运行 ai-hub CLI 命令。"""
    cmd = [sys.executable, "-m", "cli.main"] + list(args)
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}
    r = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        cwd=PROJECT_ROOT, env=env, timeout=timeout,
    )
    return r.returncode, r.stdout or "", r.stderr or ""


class TestExplainRouteScoreRouterIntegration:
    """验证 ai-hub explain-route 经过 ScoreRouter。"""

    def test_explain_route_has_strategy(self):
        """explain-route 输出包含 Strategy: 行。"""
        rc, out, err = _run_cli("explain-route", "write code", timeout=30)
        assert rc == 0, f"exit={rc} stderr={err}"
        assert "Strategy:" in out

    def test_explain_route_has_score(self):
        """explain-route 输出包含 score: 行。"""
        rc, out, err = _run_cli("explain-route", "write code", timeout=30)
        assert rc == 0, f"exit={rc} stderr={err}"
        assert "score:" in out

    def test_explain_route_json_has_schema_version(self):
        """explain-route --json 包含 schema_version。"""
        rc, out, err = _run_cli("explain-route", "write code", "--json", timeout=30)
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        assert "schema_version" in data
        assert data["schema_version"] == "2"

    def test_explain_route_json_has_runtime_version(self):
        """explain-route --json 包含 runtime_version。"""
        rc, out, err = _run_cli("explain-route", "write code", "--json", timeout=30)
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        assert "runtime_version" in data
        assert data["runtime_version"] == "0.8.2"

    def test_explain_route_json_has_strategy(self):
        """explain-route --json decision 包含 strategy。"""
        rc, out, err = _run_cli("explain-route", "write code", "--json", timeout=30)
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        dec = data.get("decision", {})
        assert "strategy" in dec

    def test_explain_route_json_has_reason(self):
        """explain-route --json decision 包含 reason。"""
        rc, out, err = _run_cli("explain-route", "write code", "--json", timeout=30)
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        dec = data.get("decision", {})
        assert "reason" in dec

    def test_explain_route_json_no_legacy_version(self):
        """explain-route --json 不应再有 'version' 字段。"""
        rc, out, err = _run_cli("explain-route", "write code", "--json", timeout=30)
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        assert "version" not in data

    def test_explain_route_json_no_legacy_group(self):
        """explain-route --json decision 不应再有 'group' 字段。"""
        rc, out, err = _run_cli("explain-route", "write code", "--json", timeout=30)
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        dec = data.get("decision", {})
        assert "group" not in dec
