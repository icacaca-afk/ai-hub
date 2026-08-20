"""Distribution packaging contracts for clean wheel installs."""

from __future__ import annotations

from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_NESTED_PACKAGES = {
    "planner.metrics",
    "planner.stages",
    "providers.claude_cli",
}


def _config() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_required_nested_packages_are_discoverable():
    discovered = {
        path.parent.relative_to(ROOT).as_posix().replace("/", ".")
        for path in ROOT.rglob("__init__.py")
        if ".git" not in path.parts
    }
    assert REQUIRED_NESTED_PACKAGES <= discovered


def test_pyproject_uses_recursive_package_discovery():
    packages = _config()["tool"]["setuptools"]["packages"]
    assert isinstance(packages, dict)
    assert "find" in packages


def test_package_discovery_is_bounded_to_project_namespaces():
    include = set(_config()["tool"]["setuptools"]["packages"]["find"]["include"])
    assert include == {
        "core*",
        "router*",
        "cli*",
        "planner*",
        "providers*",
        "adapters*",
        "scripts*",
    }


def test_test_extra_pins_compatible_mcp_major():
    test_dependencies = _config()["project"]["optional-dependencies"]["test"]
    assert "pytest>=8,<9" in test_dependencies
    assert "mcp>=1,<2" in test_dependencies
