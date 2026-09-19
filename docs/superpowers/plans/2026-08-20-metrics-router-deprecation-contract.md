# MetricsRouter Deprecation Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove 12 uncontrolled deprecation warnings from regression output while preserving and explicitly testing the V1.x compatibility shim.

**Architecture:** Keep `MetricsRouter.execute()` deprecated and functional. Replace its expired V1.0.3 removal claim with a V1.x compatibility commitment, and route every legacy test invocation through a helper that asserts the warning instead of leaking it into the suite summary.

**Tech Stack:** Python 3.11+, `warnings`, pytest 8.

---

### Task 1: Make the compatibility warning an asserted contract

**Files:**
- Modify: `router/metrics_router.py`
- Modify: `tests/test_metrics_router.py`

- [ ] **Step 1: Add a failing warning-lifecycle assertion**

Add a test that calls the legacy API through `pytest.warns`, asserts the
warning names `ExecutionPipeline + MetricsStage`, asserts V1.x compatibility,
and rejects the expired `V1.0.3` removal claim.

- [ ] **Step 2: Capture every intentional legacy call**

Add `_execute_legacy(router, task)` using `pytest.warns(DeprecationWarning)` and
replace all direct `MetricsRouter.execute()` calls in this test module. Keep
the functional assertions unchanged.

- [ ] **Step 3: Correct the production lifecycle text**

Update comments, class/method documentation, and warning text to state that the
shim is retained throughout V1.x and may be removed only through a separately
approved breaking-change ADR.

- [ ] **Step 4: Verify zero uncontrolled warnings**

Run `python -m pytest tests/test_metrics_router.py -q` and then the non-live
regression. Expected: all pass and the warnings summary contains no
`MetricsRouter.execute()` deprecation entries.

### Task 2: Close the process-owned CLI persistence connection

**Files:**
- Modify: `cli/plan.py`
- Modify: `tests/test_cli_plan.py`

- [ ] **Step 1: Add a failing cleanup contract**

Inject a fake `_SQLITE_STORE`, call `_close_runtime_state()`, and assert
`detach()` occurs before `close()`.

- [ ] **Step 2: Register process-exit cleanup**

Define `_close_runtime_state()` beside the module-owned store and register it
with `atexit`. Keep cleanup idempotent through the Store's existing `detach`
and `close` behavior.

- [ ] **Step 3: Verify interpreter shutdown is clean**

Run the non-live regression. Expected: no SQLite `ResourceWarning` after the
pytest summary.

## Self-review

- Spec coverage: all 12 warning emissions are captured without disabling
  warnings globally or weakening functional coverage.
- Placeholder scan: production wording and exact pytest mechanism are defined.
- Type consistency: the helper accepts `MetricsRouter` and `Task`, returning the
  existing `Result` unchanged.
- Resource ownership: the module that constructs and attaches the long-lived
  SQLite store is also responsible for detaching and closing it.
