"""Distribution packaging contracts for clean wheel installs."""

from __future__ import annotations

from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_NESTED_PACKAGES = {
    "planner.metrics",
    "planner.stages",
    "providers.claude_cli",
    "providers.nine_router",
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


def test_cli_is_regular_package_to_avoid_third_party_module_collision():
    assert (ROOT / "cli" / "__init__.py").is_file()


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


def test_distribution_version_comes_from_runtime_source():
    config = _config()
    assert "version" not in config["project"]
    assert "version" in config["project"]["dynamic"]
    assert config["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "cli.version.__version__",
    }


def test_runtime_and_pipeline_versions_match():
    from cli import version
    from cli.pipeline_inspect import RUNTIME_VERSION

    assert version.__version__ == "1.0.13"
    assert RUNTIME_VERSION == version.__version__


def test_mcp_runtime_extra_is_declared():
    """V1.0.13 审核 P1：MCP 适配器必须有可安装的运行时 extra。"""
    extras = _config()["project"]["optional-dependencies"]
    assert extras["mcp"] == ["mcp>=1,<2"]


def test_mcp_adapter_documented_for_installs():
    """双语 README 必须写明 [mcp] extra 与 wheel 安装态的正确入口。"""
    for name in ("README.md", "README.zh-CN.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert '".[mcp]"' in text, name
        assert "python -m adapters.marvis_mcp_server" in text, name
