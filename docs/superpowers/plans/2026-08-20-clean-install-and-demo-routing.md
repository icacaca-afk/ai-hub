# Clean Install and Deterministic Demo Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI Hub installable from a real wheel and provide account-free, deterministic `ask` and `plan` acceptance commands.

**Architecture:** Replace the stale explicit setuptools package list with bounded recursive discovery. Add a CLI-only provider-selection helper that narrows a registry before constructing the existing Router; default routing and frozen runtime contracts remain unchanged.

**Tech Stack:** Python 3.11+, setuptools, pytest 8, existing Provider/Bridge/Router abstractions, PowerShell 7 verification.

---

## File structure

- Create `cli/provider_selection.py`: parse `--provider` and build a narrowed registry.
- Create `tests/test_cli_provider_selection.py`: option, registry, `ask`, and real Demo `plan` contracts.
- Create `tests/test_packaging.py`: nested-package and pyproject discovery contracts.
- Modify `cli/main.py`: apply the helper to `ask` and update help.
- Modify `cli/plan.py`: apply the helper to `plan` and update usage.
- Modify `pyproject.toml`: recursive package discovery and `test` extra.
- Modify maintained English/Chinese README, architecture, and roadmap documents together.

### Task 1: Lock the packaging contract

**Files:**
- Create: `tests/test_packaging.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing discovery tests**

```python
from pathlib import Path
import tomllib
from setuptools import find_packages

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = {"planner.metrics", "planner.stages", "providers.claude_cli"}

def test_required_nested_packages_are_discoverable():
    assert REQUIRED <= set(find_packages(where=ROOT))

def test_pyproject_uses_recursive_package_discovery():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    setuptools = config["tool"]["setuptools"]
    assert "find" in setuptools["packages"]
    assert "packages" not in setuptools or not isinstance(setuptools.get("packages"), list)

def test_test_extra_pins_compatible_mcp_major():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "mcp>=1,<2" in config["project"]["optional-dependencies"]["test"]
```

- [ ] **Step 2: Run the tests and verify the pyproject assertions fail**

Run: `python -m pytest tests/test_packaging.py -q`

Expected: discovery succeeds but pyproject configuration assertions fail.

- [ ] **Step 3: Replace the manual package list**

```toml
[project.optional-dependencies]
test = ["pytest>=8,<9", "mcp>=1,<2"]

[tool.setuptools.packages.find]
include = ["core*", "router*", "cli*", "planner*", "providers*", "adapters*", "scripts*"]
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_packaging.py -q`

Expected: all pass.

### Task 2: Add explicit provider selection

**Files:**
- Create: `cli/provider_selection.py`
- Create: `tests/test_cli_provider_selection.py`

- [ ] **Step 1: Write failing parser and registry tests**

Cover `--provider demo`, `--provider=demo`, missing values, duplicates, unknown
providers, preserved argument order, and a narrowed registry containing exactly
the selected Provider.

- [ ] **Step 2: Verify failure**

Run: `python -m pytest tests/test_cli_provider_selection.py -q`

Expected: import fails because `cli.provider_selection` does not exist.

- [ ] **Step 3: Implement the helper**

```python
def extract_provider_option(args: list[str]) -> tuple[list[str], str | None]: ...
def narrow_registry(registry, provider_name: str | None): ...
```

`extract_provider_option` raises `ValueError` before execution for malformed or
duplicate options. `narrow_registry` raises `ValueError` for unknown names and
returns the original registry when no name is supplied.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_cli_provider_selection.py -q`

Expected: helper tests pass.

### Task 3: Wire `ask` and `plan`

**Files:**
- Modify: `cli/main.py`
- Modify: `cli/plan.py`
- Modify: `tests/test_cli_provider_selection.py`

- [ ] **Step 1: Add command tests**

Test that `cmd_ask(["hello", "--provider", "demo"])` and
`cmd_plan(["hello", "then", "world", "--provider", "demo", "--json"])
construct their routers from a narrowed registry, remove the option from task
text, and keep JSON stdout pure. Test malformed and unknown provider inputs exit
1 without constructing a Router.

- [ ] **Step 2: Add parsing before runtime construction**

Both commands call `extract_provider_option`, report `Error: ...` to stderr,
print their exact usage, and exit 1 on `ValueError`. After `_build_registry()`,
both call `narrow_registry` before creating the existing Router.

- [ ] **Step 3: Run focused regressions**

Run:

```powershell
python -m pytest tests/test_cli_provider_selection.py tests/test_cli_plan.py `
  tests/test_cli_plan_json.py tests/test_cli_pipeline_inspect.py -q
```

Expected: all pass.

### Task 4: Prove the wheel and local E2E path

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ARCHITECTURE.zh-CN.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/ROADMAP.zh-CN.md`

- [ ] **Step 1: Build a wheel**

Run: `python -m pip wheel . --no-deps --wheel-dir <artifact-dir>`

Expected: one wheel is created.

- [ ] **Step 2: Install outside the source tree**

Create a clean venv, install the wheel, change directory to `C:\Windows\Temp`,
and import `planner.metrics`, `planner.stages`, and
`providers.claude_cli.provider`.

Expected: exit 0 and `wheel imports ok`.

- [ ] **Step 3: Run deterministic commands from the wheel**

```powershell
ai-hub ask "hello" --provider demo
ai-hub plan "say hello then summarize it" --provider demo --json
ai-hub pipeline inspect --json
```

Expected: all exit 0; both JSON outputs parse; `ask` reports Demo.

- [ ] **Step 4: Update bilingual docs**

Document `--provider demo` as the account-free smoke path, package discovery as
a release invariant, and the exact clean-wheel verification commands in both
maintained languages.

- [ ] **Step 5: Run release checks**

```powershell
git diff --check
python -m pytest tests/test_provider_contract.py::test_zero_modification_kpi -q
python -m pytest tests/test_cli_provider_selection.py tests/test_packaging.py `
  tests/test_cli_plan.py tests/test_cli_plan_json.py tests/test_cli_pipeline_inspect.py -q
```

Expected: zero failures and no frozen-boundary changes.

## Self-review

- Spec coverage: wheel completeness, deterministic provider pinning, real CLI
  execution, test dependencies, frozen boundaries, and bilingual docs are each
  mapped to a task.
- Placeholder scan: no implementation step depends on an undefined production
  API; test cases enumerate all parser errors.
- Type consistency: both command paths consume
  `tuple[list[str], str | None]`; registry narrowing returns the original
  registry or a `CapabilityRegistry` with one Provider.
