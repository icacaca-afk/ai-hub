"""CLI-only explicit Provider selection helpers."""

from __future__ import annotations

from core.registry import CapabilityRegistry


def extract_provider_option(args: list[str]) -> tuple[list[str], str | None]:
    """Remove one ``--provider`` option and return its value.

    Both ``--provider NAME`` and ``--provider=NAME`` are accepted. Invalid or
    duplicate forms fail before a Router or Provider is constructed.
    """
    remaining: list[str] = []
    provider_name: str | None = None
    index = 0

    while index < len(args):
        argument = args[index]
        if argument == "--provider":
            if provider_name is not None:
                raise ValueError("--provider may be specified only once")
            if (
                index + 1 >= len(args)
                or not args[index + 1].strip()
                or args[index + 1].startswith("--")
            ):
                raise ValueError("--provider requires a provider name")
            provider_name = args[index + 1].strip()
            index += 2
            continue
        if argument.startswith("--provider="):
            if provider_name is not None:
                raise ValueError("--provider may be specified only once")
            provider_name = argument.partition("=")[2].strip()
            if not provider_name:
                raise ValueError("--provider requires a provider name")
            index += 1
            continue
        remaining.append(argument)
        index += 1

    return remaining, provider_name


def narrow_registry(registry, provider_name: str | None):
    """Return a registry containing only the explicitly selected Provider."""
    if provider_name is None:
        return registry

    provider = registry.get(provider_name)
    if provider is None:
        available = ", ".join(sorted(item.name for item in registry.all()))
        suffix = f" Available providers: {available}." if available else ""
        raise ValueError(f"Unknown provider: {provider_name}.{suffix}")

    selected = CapabilityRegistry()
    selected.register(provider)
    return selected


__all__ = ["extract_provider_option", "narrow_registry"]
