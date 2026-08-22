# Trae CLI Provider Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended; inline execution is authorized for this request). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal AI Hub Provider that can dispatch a bounded, read-only review task to the locally installed Trae CLI.

**Architecture:** Reuse the existing `Provider`/`CLIBridge` boundary and register a `TraeCLIProvider` in the existing CLI registries. The first dispatch is explicitly provider-pinned and read-only; no Core, Router, or existing Provider changes are allowed.

**Tech Stack:** Python 3.11+, existing `CLIBridge`, Trae CLI `trae-cli -p`, pytest 8, PowerShell 7.

---

### Task 1: Lock the Trae Provider contract

**Files:**
- Create: `providers/trae_cli/__init__.py`
- Create: `providers/trae_cli/provider.py`
- Modify: `tests/test_provider_contract.py`

- [ ] **Step 1: Add the contract test**

Import `TraeCLIProvider`, run `check_contract(TraeCLIProvider)`, and assert no
violations. Add its declared capabilities to the metadata consistency list.

- [ ] **Step 2: Verify the test fails**

Run: `python -m pytest tests/test_provider_contract.py -q`

Expected: import failure because `providers.trae_cli` does not exist.

- [ ] **Step 3: Implement the minimal provider**

Use `CLIBridge` with `command="trae-cli"`, `version_command="trae-cli --version"`,
`command_template='trae-cli -p "{task}" --output-format text'`, and a bounded
900-second task timeout. Declare `code.review`, `code.refactor`,
`text.summarize`, and `general.chat`; `health()` returns `HealthReport`.

- [ ] **Step 4: Run the contract test**

Run: `python -m pytest tests/test_provider_contract.py -q`

Expected: all Provider contracts pass without invoking a real Trae task.

### Task 2: Register and dispatch a read-only audit

**Files:**
- Modify: `cli/main.py`
- Modify: `cli/plan.py`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] **Step 1: Register `TraeCLIProvider`**

Add it to both `_build_registry()` functions so `ask --provider trae_cli` and
`plan --provider trae_cli` use the same Provider boundary.

- [ ] **Step 2: Verify deterministic routing**

Run `ai-hub ask "return only the provider name" --provider trae_cli` and confirm
the router selects Trae before executing.

- [ ] **Step 3: Dispatch the bounded audit**

Run from the AI Hub worktree:

```powershell
ai-hub ask "<read-only multi-agent-loop audit prompt>" --provider trae_cli
```

The prompt must forbid edits, commits, pushes, destructive commands, and
external messages; it asks for findings, priorities, and a proposed next ADR.

- [ ] **Step 4: Record the evidence**

Save the Trae response and command metadata under `.artifacts/trae-audit/` and
do not apply any suggested changes automatically.

### Task 3: Validate the integration

- [ ] **Step 1:** Run provider contract and CLI provider-selection tests.
- [ ] **Step 2:** Run `git diff --check` and the zero-modification KPI test.
- [ ] **Step 3:** Report whether Trae was available/authenticated and whether the
audit completed, timed out, or failed.

## Self-review

- Scope covers provider contract, both CLI registries, a read-only dispatch, and
evidence capture.
- No Core, Router, or existing Provider file is changed.
- The first task cannot modify the repository, so external agent suggestions
remain review input rather than untrusted code.
