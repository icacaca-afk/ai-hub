"""Declarative predicate metadata (V1.0.12, ADR-0033)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PredicateDescriptor:
    """Immutable semantic description of a condition predicate.

    The descriptor contains user-declared metadata only. It never contains or
    inspects the executable callable.
    """

    name: str
    description: str = ""
    subject: str = ""

    def to_dict(self) -> dict[str, str]:
        """Delegate to the canonical metadata serializer."""
        from planner.metadata_serialization import serialize_predicate

        return serialize_predicate(self)


__all__ = ["PredicateDescriptor"]
