# Release Metadata and Bounded MCP Introspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate release-version drift and make the complete MCP contract suite deterministic and bounded.

**Architecture:** Define the runtime/package version once in `cli/version.py` and let setuptools read it dynamically. Make MCP Provider listing metadata-only by default; callers may explicitly request availability probes, while the contract client reads subprocess output through a bounded queue instead of blocking directly on `readline()`.

**Tech Stack:** Python 3.11+, setuptools dynamic metadata, FastMCP 1.x, pytest 8, PowerShell 7.

---

## File structure

- Create `cli/version.py`: canonical AI Hub distribution/runtime version.
- Modify `pyproject.toml`: use setuptools dynamic version metadata.
- Modify `cli/pipeline_inspect.py`: import the canonical runtime version.
- Modify `tests/test_packaging.py`: assert package and runtime versions share one source.
- Modify `adapters/marvis_mcp_server.py`: return metadata without external probes by default and expose opt-in probing.
- Modify `tests/test_mcp_contract.py`: enforce real response deadlines and cover non-probing/probing contracts.
- Modify maintained English/Chinese documentation and ADR-0037 together.

### Task 1: Establish a single version source

**Files:**
- Create: `cli/version.py`
- Modify: `pyproject.toml`
- Modify: `cli/pipeline_inspect.py`
- Modify: `tests/test_packaging.py`

- [ ] **Step 1: Add failing metadata tests**

Assert that `project.dynamic` contains `version`, that
`tool.setuptools.dynamic.version.attr == "cli.version.__version__"`, and that
`cli.pipeline_inspect.RUNTIME_VERSION == cli.version.__version__ == "1.0.13"`.

- [ ] **Step 2: Verify the tests fail**

Run: `python -m pytest tests/test_packaging.py -q`

Expected: failure because `pyproject.toml` still contains static `0.0.1` and
`cli.version` does not exist.

- [ ] **Step 3: Implement dynamic metadata**

Create:

```python
__version__ = "1.0.13"
```

Replace the static project version with `dynamic = ["version"]`, configure
setuptools to read `cli.version.__version__`, and import it as
`RUNTIME_VERSION` in pipeline inspection.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_packaging.py tests/test_cli_pipeline_inspect.py -q`

Expected: all pass.

### Task 2: Bound MCP introspection and its contract client

**Files:**
- Modify: `adapters/marvis_mcp_server.py`
- Modify: `tests/test_mcp_contract.py`

- [ ] **Step 1: Add failing list-provider unit contracts**

Call `list_providers()` directly with a fake registry. Assert the default call
does not invoke `Provider.available()`, returns `available: null` and
`availability: "unchecked"`, while `list_providers(probe_availability=True)`
does invoke it and returns `availability: "available"` or `"unavailable"`.

- [ ] **Step 2: Add a real response deadline**

Start one daemon reader thread per MCP subprocess, push stdout lines into a
`queue.Queue`, and have `read_response()` use `queue.get(timeout=remaining)`.
On timeout include recent stderr and process status in the raised error.

- [ ] **Step 3: Implement metadata-only listing**

Change the MCP signature to:

```python
def list_providers(probe_availability: bool = False) -> dict:
```

The default path must not call `available()`. The explicit probe preserves the
existing availability behavior and labels whether the value was checked.

- [ ] **Step 4: Run MCP contracts**

Run: `python -m pytest tests/test_mcp_contract.py -q`

Expected: all tests finish within their configured deadline and pass.

### Task 3: Document and prove the release artifact

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ARCHITECTURE.zh-CN.md`
- Modify: `docs/adr/0037-clean-install-and-deterministic-demo.md`

- [ ] **Step 1: Update maintained documentation**

Remove the `0.0.1` mismatch warning, describe the single version source, and
document that MCP Provider listing is non-probing unless availability probing
is explicitly requested.

- [ ] **Step 2: Build and inspect a clean wheel**

Run `python -m pip wheel . --no-deps --wheel-dir <artifact-dir>`, install it in
a new virtual environment, and assert `importlib.metadata.version("ai-hub") ==
"1.0.13"` outside the source tree.

- [ ] **Step 3: Run regression and artifact gates**

Run focused version/MCP/CLI tests, the non-live regression suite, external
wheel Demo commands, `git diff --check`, and the frozen-boundary test.

Expected: zero failures and wheel filename `ai_hub-1.0.13-py3-none-any.whl`.

## Self-review

- Spec coverage: the plan covers both known release gaps, their regression
  tests, user-facing documentation, and clean-wheel evidence.
- Placeholder scan: every production behavior has a concrete signature,
  return-state contract, and exact verification command.
- Type consistency: `probe_availability` is a Boolean in the FastMCP schema;
  `available` is `bool | None`; `availability` is always a string state.
