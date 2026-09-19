"""All public surfaces must consume the canonical Provider registry."""

from __future__ import annotations


def _names(registry) -> list[str]:
    return [provider.name for provider in registry.all()]


def test_canonical_registry_contains_nine_router_exactly_once(monkeypatch):
    monkeypatch.delenv("NINE_ROUTER_ENABLED", raising=False)
    from cli.provider_registry import build_default_registry

    names = _names(build_default_registry())

    assert names.count("nine_router") == 1


def test_explain_route_uses_canonical_registry(monkeypatch):
    monkeypatch.delenv("NINE_ROUTER_ENABLED", raising=False)
    from cli.explain_route import _build_registry
    from cli.provider_registry import build_default_registry

    assert _names(_build_registry()) == _names(build_default_registry())


def test_mcp_uses_canonical_registry_without_network_probe(monkeypatch):
    monkeypatch.delenv("NINE_ROUTER_ENABLED", raising=False)
    from adapters import marvis_mcp_server as server
    from cli.provider_registry import build_default_registry
    from providers.nine_router.provider import NineRouterBridge

    monkeypatch.setattr(server, "_registry", None)
    monkeypatch.setattr(
        NineRouterBridge,
        "_open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("metadata registry construction must not probe 9Router")
        ),
    )

    actual = server._get_registry()

    assert _names(actual) == _names(build_default_registry())
    listing = server.list_providers()
    nine_router = next(
        item for item in listing["providers"] if item["name"] == "nine_router"
    )
    assert nine_router["available"] is None
    assert nine_router["availability"] == "unchecked"
