"""Explicit CLI provider selection and deterministic Demo execution tests."""

from __future__ import annotations

import json

import pytest

from core.registry import CapabilityRegistry
from providers.demo.provider import DemoProvider


class TestExtractProviderOption:
    def test_separate_value(self):
        from cli.provider_selection import extract_provider_option

        remaining, provider = extract_provider_option(
            ["hello", "--provider", "demo", "world"]
        )
        assert remaining == ["hello", "world"]
        assert provider == "demo"

    def test_equals_value(self):
        from cli.provider_selection import extract_provider_option

        remaining, provider = extract_provider_option(["hello", "--provider=demo"])
        assert remaining == ["hello"]
        assert provider == "demo"

    def test_absent_option_preserves_arguments(self):
        from cli.provider_selection import extract_provider_option

        args = ["hello", "then", "world"]
        assert extract_provider_option(args) == (args, None)

    @pytest.mark.parametrize(
        "args",
        [
            ["hello", "--provider"],
            ["hello", "--provider", "--json"],
            ["hello", "--provider="],
            ["--provider", "demo", "--provider", "demo", "hello"],
            ["--provider=demo", "--provider=demo", "hello"],
        ],
    )
    def test_malformed_options_raise(self, args):
        from cli.provider_selection import extract_provider_option

        with pytest.raises(ValueError):
            extract_provider_option(args)


class TestNarrowRegistry:
    def test_none_returns_original_registry(self):
        from cli.provider_selection import narrow_registry

        registry = CapabilityRegistry()
        assert narrow_registry(registry, None) is registry

    def test_selected_registry_contains_only_named_provider(self):
        from cli.provider_selection import narrow_registry

        registry = CapabilityRegistry()
        demo = DemoProvider()
        registry.register(demo)
        selected = narrow_registry(registry, "demo")
        assert selected is not registry
        assert selected.all() == [demo]

    def test_unknown_provider_reports_available_names(self):
        from cli.provider_selection import narrow_registry

        registry = CapabilityRegistry()
        registry.register(DemoProvider())
        with pytest.raises(ValueError, match="demo"):
            narrow_registry(registry, "missing")


class TestProviderPinnedCommands:
    def test_ask_runs_demo_and_strips_option(self, capsys):
        from cli.main import cmd_ask

        cmd_ask(["hello", "--provider", "demo"])
        captured = capsys.readouterr()
        assert "Provider:     Demo" in captured.out
        assert "You said: hello" in captured.out
        assert "--provider" not in captured.out

    def test_plan_runs_demo_and_keeps_json_pure(self, monkeypatch, capsys):
        from cli import plan as plan_module

        monkeypatch.setattr(plan_module, "_EVENT_BUS", None)
        plan_module.cmd_plan(
            ["say hello", "then", "summarize it", "--provider", "demo", "--json"]
        )
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert captured.err == ""
        assert payload["plan"]["status"] == "success"
        assert payload["plan"]["metadata"]["plan"]["steps"] == 2
        assert "--provider" not in payload["plan"]["output"]

    @pytest.mark.parametrize(
        "command,args",
        [
            ("ask", ["hello", "--provider"]),
            ("ask", ["hello", "--provider", "missing"]),
            ("plan", ["hello", "--provider"]),
            ("plan", ["hello", "--provider", "missing"]),
        ],
    )
    def test_provider_errors_exit_before_router_execution(
        self, command, args, monkeypatch, capsys
    ):
        if command == "ask":
            import cli.main as module

            monkeypatch.setattr(
                module,
                "ScoreRouter",
                lambda *a, **k: (_ for _ in ()).throw(
                    AssertionError("router must not be constructed")
                ),
            )
            target = module.cmd_ask
        else:
            import cli.plan as module

            monkeypatch.setattr(
                module,
                "MetricsRouter",
                lambda *a, **k: (_ for _ in ()).throw(
                    AssertionError("router must not be constructed")
                ),
            )
            target = module.cmd_plan

        with pytest.raises(SystemExit) as exc:
            target(args)
        assert exc.value.code == 1
        assert "Error:" in capsys.readouterr().err
