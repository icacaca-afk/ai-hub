# tests/test_cli_score_integration.py
# V0.8.2 — CLI ScoreRouter Integration Regression Test
#
# 入口级保护：验证 ai-hub explain-route 经过 ScoreRouter。
# 只测 explain-route（不实际执行 Provider），避免 subprocess 超时。

import sys
import json

import pytest
from core.registry import CapabilityRegistry
from providers.demo.provider import DemoProvider


class _NeverExhaustedQuota:
    """Deterministic quota stub for route-explanation contract tests."""

    def exhausted(self, _provider_name):
        return False


@pytest.fixture
def run_cli(monkeypatch, capsys):
    """Run the real CLI dispatcher with a deterministic local registry.

    These are non-live contract tests.  They must not probe installed CLIs,
    browsers, credentials, or network services merely to verify output shape.
    """
    import cli.explain_route as explain_route_module
    import cli.main as main_module

    def build_registry():
        registry = CapabilityRegistry()
        registry.register(DemoProvider())
        return registry

    monkeypatch.setattr(explain_route_module, "_build_registry", build_registry)
    monkeypatch.setattr(
        explain_route_module,
        "QuotaManager",
        lambda: _NeverExhaustedQuota(),
    )

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["ai-hub", *args])
        try:
            main_module.main()
            returncode = 0
        except SystemExit as exc:
            returncode = int(exc.code or 0)
        captured = capsys.readouterr()
        return returncode, captured.out or "", captured.err or ""

    return invoke


class TestExplainRouteScoreRouterIntegration:
    """验证 ai-hub explain-route 经过 ScoreRouter。"""

    def test_explain_route_has_strategy(self, run_cli):
        """explain-route 输出包含 Strategy: 行。"""
        rc, out, err = run_cli("explain-route", "write code")
        assert rc == 0, f"exit={rc} stderr={err}"
        assert "Strategy:" in out

    def test_explain_route_has_score(self, run_cli):
        """explain-route 输出包含 score: 行。"""
        rc, out, err = run_cli("explain-route", "write code")
        assert rc == 0, f"exit={rc} stderr={err}"
        assert "score:" in out

    def test_explain_route_json_has_schema_version(self, run_cli):
        """explain-route --json 包含 schema_version。"""
        rc, out, err = run_cli("explain-route", "write code", "--json")
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        assert "schema_version" in data
        assert data["schema_version"] == "2"

    def test_explain_route_json_has_runtime_version(self, run_cli):
        """explain-route --json 包含 runtime_version。"""
        rc, out, err = run_cli("explain-route", "write code", "--json")
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        assert "runtime_version" in data
        assert data["runtime_version"] == "0.8.2"

    def test_explain_route_json_has_strategy(self, run_cli):
        """explain-route --json decision 包含 strategy。"""
        rc, out, err = run_cli("explain-route", "write code", "--json")
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        dec = data.get("decision", {})
        assert "strategy" in dec

    def test_explain_route_json_has_reason(self, run_cli):
        """explain-route --json decision 包含 reason。"""
        rc, out, err = run_cli("explain-route", "write code", "--json")
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        dec = data.get("decision", {})
        assert "reason" in dec

    def test_explain_route_json_no_legacy_version(self, run_cli):
        """explain-route --json 不应再有 'version' 字段。"""
        rc, out, err = run_cli("explain-route", "write code", "--json")
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        assert "version" not in data

    def test_explain_route_json_no_legacy_group(self, run_cli):
        """explain-route --json decision 不应再有 'group' 字段。"""
        rc, out, err = run_cli("explain-route", "write code", "--json")
        assert rc == 0, f"exit={rc} stderr={err}"
        data = json.loads(out)
        dec = data.get("decision", {})
        assert "group" not in dec
