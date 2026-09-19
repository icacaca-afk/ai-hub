# 9Router Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 9Router as an explicitly enabled, manually selected, security-bounded downstream Provider without changing AI Hub core/router semantics or Multi-Agent Loop Phase 3.

**Architecture:** AI Hub remains the task and Provider router; a thin `NineRouterProvider` delegates one fixed model or Combo to 9Router's OpenAI-compatible `/v1` HTTP API. Configuration is immutable and validated before network access, the Provider is disabled by default and manual-only for V1.0.14, and all CLI/MCP surfaces consume the canonical provider registry.

**Tech Stack:** Python 3.11+, standard-library `urllib`, pytest, AI Hub Provider/Bridge contracts, local mock HTTP server.

---

## File map

- Create `docs/adr/0038-nine-router-provider.md`: Proposed design, security boundary, rollout, and rollback.
- Create `providers/nine_router/__init__.py`: public exports only.
- Create `providers/nine_router/config.py`: immutable environment parsing and URL/auth validation.
- Create `providers/nine_router/provider.py`: HTTP bridge and thin Provider declaration.
- Create `tests/test_nine_router_config.py`: configuration/security tests.
- Create `tests/test_nine_router_provider.py`: mock-server bridge, health, and error tests.
- Modify `cli/provider_selection.py`: generic opt-in hook for manual-only Providers.
- Modify `cli/provider_registry.py`: register 9Router once in the canonical registry.
- Modify `cli/explain_route.py`: consume the canonical registry instead of a duplicate list.
- Modify `adapters/marvis_mcp_server.py`: consume the canonical registry instead of a duplicate list.
- Modify `tests/test_cli_provider_selection.py`: manual-selection hook tests.
- Modify `tests/test_provider_contract.py`: Provider contract and capability metadata.
- Modify `tests/test_mcp_contract.py`: canonical registry parity and metadata-only behavior.
- Modify `tests/test_packaging.py`: wheel package inclusion.
- Modify `README.md` and `README.zh-CN.md`: explicit configuration and limitations.

### Task 1: Accept the design boundary

**Files:**
- Create: `docs/adr/0038-nine-router-provider.md`

- [ ] **Step 1: Write the ADR as Proposed**

The ADR must state all of these decisions explicitly:

```text
NINE_ROUTER_ENABLED=1 is required.
NINE_ROUTER_MODEL is required and is never inferred from list order.
NINE_ROUTER_API_KEY is required unless loopback and NINE_ROUTER_ALLOW_NO_AUTH=1.
Non-loopback endpoints require HTTPS.
URL userinfo, query, and fragment are rejected.
Redirects are rejected; loopback bypasses system proxies.
X-9Router-Token-Saver defaults to off.
The Provider is manual-only in V1.0.14.
No core/, router/, or Multi-Agent Loop Phase 3 files change.
Reachable/model-present health is degraded, not proof of successful execution.
```

- [ ] **Step 2: Check numbering and frozen paths**

Run: `Get-ChildItem docs/adr | Sort-Object Name`

Expected: `0037-clean-install-and-deterministic-demo.md` remains untouched and the new ADR is `0038-nine-router-provider.md`.

- [ ] **Step 3: Commit**

```text
git add docs/adr/0038-nine-router-provider.md
git commit -m "docs: propose bounded 9Router provider"
```

### Task 2: Validate immutable configuration before networking

**Files:**
- Create: `providers/nine_router/__init__.py`
- Create: `providers/nine_router/config.py`
- Create: `tests/test_nine_router_config.py`

- [ ] **Step 1: Write failing configuration tests**

Cover these named cases in `tests/test_nine_router_config.py`:

```python
def test_disabled_defaults_are_safe_and_network_free(): ...
def test_enabled_requires_explicit_model(): ...
def test_enabled_requires_key_without_explicit_loopback_no_auth(): ...
def test_loopback_no_auth_requires_both_loopback_and_opt_in(): ...
def test_remote_endpoint_requires_https(): ...
def test_url_rejects_userinfo_query_and_fragment(): ...
def test_token_saver_defaults_off_and_requires_explicit_opt_in(): ...
def test_timeout_must_be_positive_and_bounded(): ...
```

Use `monkeypatch.delenv/setenv` for every `NINE_ROUTER_*` setting; do not depend on the developer machine environment.

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_nine_router_config.py -q`

Expected: FAIL because `providers.nine_router.config` does not exist.

- [ ] **Step 3: Implement the exact configuration surface**

```python
@dataclass(frozen=True)
class NineRouterConfig:
    enabled: bool
    base_url: str
    model: str
    api_key: str
    allow_no_auth: bool
    token_saver: bool
    timeout: float

    @classmethod
    def from_env(cls) -> "NineRouterConfig": ...

    @classmethod
    def disabled(cls) -> "NineRouterConfig": ...

    @property
    def is_loopback(self) -> bool: ...

    @property
    def authentication_allowed(self) -> bool:
        return bool(self.api_key) or (self.is_loopback and self.allow_no_auth)
```

`from_env()` accepts only `1` as enabled for the three boolean switches, defaults the base URL to `http://127.0.0.1:20128/v1`, strips one trailing slash, requires a positive timeout no greater than 300 seconds, and raises `ValueError` before any request when an enabled configuration violates the ADR.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_nine_router_config.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```text
git add providers/nine_router tests/test_nine_router_config.py
git commit -m "feat: validate 9Router configuration"
```

### Task 3: Implement a bounded non-streaming HTTP bridge

**Files:**
- Create: `providers/nine_router/provider.py`
- Create: `tests/test_nine_router_provider.py`

- [ ] **Step 1: Write failing bridge tests**

Build a local `ThreadingHTTPServer` fixture that records method, path, headers, and JSON body. Add tests for:

```python
def test_disabled_bridge_never_opens_network(...): ...
def test_fixed_model_executes_without_using_first_model(...): ...
def test_missing_fixed_model_returns_structured_failure(...): ...
def test_combo_identifier_is_treated_as_an_exact_model_id(...): ...
def test_loopback_bypasses_http_and_https_proxy(...): ...
def test_token_saver_header_defaults_off(...): ...
def test_token_saver_header_explicitly_turns_on(...): ...
def test_redirect_is_rejected_without_forwarding_authorization(...): ...
@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_http_errors_are_bounded_and_structured(status, ...): ...
def test_timeout_connection_failure_empty_models_and_invalid_json_are_failures(...): ...
def test_error_text_redacts_api_key_and_is_at_most_2048_characters(...): ...
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_nine_router_provider.py -q`

Expected: FAIL because `NineRouterBridge` and `NineRouterProvider` are absent.

- [ ] **Step 3: Implement the bridge contract**

```python
class NineRouterBridge(Bridge):
    def __init__(self, config: NineRouterConfig): ...
    def list_models(self) -> list[str]: ...
    def run(self, task: Task, **kwargs) -> BridgeResult: ...
    def check_available(self) -> bool: ...
```

Implementation rules:

- `run()` always uses `config.model`; it ignores model overrides and never selects `models[0]`.
- `list_models()` is only validation/diagnostics and requires the configured identifier to exist exactly.
- Requests are `POST /chat/completions`, `stream=false`, one user message, with `X-9Router-Token-Saver: off|on`.
- A custom `HTTPRedirectHandler` rejects every redirect.
- Loopback uses `ProxyHandler({})`; remote HTTPS uses normal proxy handling.
- HTTP/URL/timeout/JSON/schema errors become `BridgeResult(success=False, ...)`.
- Error text is redacted and capped at 2048 characters; secrets never enter `raw` on failure.
- No tool calls, streaming, images, audio, artifacts, or arbitrary `extra_body` are accepted in V1.0.14.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_nine_router_config.py tests/test_nine_router_provider.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```text
git add providers/nine_router tests/test_nine_router_provider.py
git commit -m "feat: add bounded 9Router bridge"
```

### Task 4: Enforce manual-only routing and honest health

**Files:**
- Modify: `providers/nine_router/provider.py`
- Modify: `cli/provider_selection.py`
- Modify: `tests/test_nine_router_provider.py`
- Modify: `tests/test_cli_provider_selection.py`

- [ ] **Step 1: Write failing selection and health tests**

```python
def test_enabled_provider_is_not_available_before_explicit_selection(...): ...
def test_narrow_registry_marks_manual_provider_explicit(...): ...
def test_explicit_selection_allows_available_check(...): ...
def test_reachable_model_health_is_degraded_not_healthy(...): ...
def test_disabled_missing_model_and_missing_auth_health_do_not_touch_network(...): ...
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `python -m pytest tests/test_cli_provider_selection.py tests/test_nine_router_provider.py -q`

Expected: new tests fail because the hook and manual-only state do not exist.

- [ ] **Step 3: Add a generic explicit-selection hook**

In `narrow_registry`, after resolving the requested Provider:

```python
mark_explicit = getattr(provider, "mark_explicit_selection", None)
if callable(mark_explicit):
    mark_explicit()
```

In `NineRouterProvider`:

```python
manual_only = True

def mark_explicit_selection(self) -> None:
    self._explicitly_selected = True

def available(self) -> bool:
    return self._explicitly_selected and super().available()
```

`health()` returns unavailable for disabled/invalid configuration without I/O. When the gateway is reachable and the fixed model exists, it returns `HealthReport(status="degraded", authenticated=True, quota_ok=None, message="reachable; execution not yet verified")`; it never reports fully healthy from `/models` alone.

- [ ] **Step 4: Run focused tests and commit**

Run: `python -m pytest tests/test_cli_provider_selection.py tests/test_nine_router_provider.py -q`

Expected: all tests pass.

```text
git add cli/provider_selection.py providers/nine_router/provider.py tests
git commit -m "feat: keep 9Router explicit and health-honest"
```

### Task 5: Register once and expose metadata consistently

**Files:**
- Modify: `cli/provider_registry.py`
- Modify: `cli/explain_route.py`
- Modify: `adapters/marvis_mcp_server.py`
- Modify: `tests/test_provider_contract.py`
- Modify: `tests/test_mcp_contract.py`
- Modify: `tests/test_packaging.py`

- [ ] **Step 1: Write failing parity tests**

Add assertions that `nine_router` appears exactly once in the canonical registry, passes `check_contract`, declares only known capabilities, is present in default MCP metadata without probing, and `providers.nine_router` is a required nested wheel package. Assert MCP metadata leaves availability `unchecked`, so listing never contacts 9Router.

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest tests/test_provider_contract.py tests/test_mcp_contract.py tests/test_packaging.py -q`

Expected: new assertions fail because the Provider is not registered or packaged.

- [ ] **Step 3: Remove duplicate registry definitions**

Register `NineRouterProvider()` in `build_default_registry()`. Make `cli.explain_route._build_registry()` return `build_default_registry()`. Make MCP `_get_registry()` lazily call the same builder. Do not add imports or registrations to `cli/main.py` or `cli/plan.py`.

- [ ] **Step 4: Run focused tests and commit**

Run: `python -m pytest tests/test_provider_contract.py tests/test_mcp_contract.py tests/test_packaging.py tests/test_explain_route.py -q`

Expected: all tests pass and metadata listing performs zero external probes.

```text
git add cli adapters tests
git commit -m "refactor: share canonical provider registry"
```

### Task 6: Document safe use and rollback

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/adr/0038-nine-router-provider.md`

- [ ] **Step 1: Add bilingual examples**

Document the exact PowerShell variables and explicit invocation:

```powershell
$env:NINE_ROUTER_ENABLED = '1'
$env:NINE_ROUTER_BASE_URL = 'http://127.0.0.1:20128/v1'
$env:NINE_ROUTER_MODEL = 'approved-provider/model-or-combo'
$env:NINE_ROUTER_API_KEY = 'dedicated-test-key'
ai-hub ask 'hello' --provider nine_router
```

For a local no-auth gateway, document that both loopback and `NINE_ROUTER_ALLOW_NO_AUTH=1` are required. State that Token Saver, Cloud Sync/Tunnel, prompt-style injection, MITM credential reuse, and automatic routing are not enabled by this integration.

- [ ] **Step 2: Add documentation assertions**

Extend packaging or a dedicated documentation test to require both READMEs to contain `NINE_ROUTER_ENABLED`, `NINE_ROUTER_MODEL`, `--provider nine_router`, and `X-9Router-Token-Saver` default-off wording.

- [ ] **Step 3: Run and commit**

Run: `python -m pytest tests/test_packaging.py -q`

Expected: pass.

```text
git add README.md README.zh-CN.md docs/adr/0038-nine-router-provider.md tests/test_packaging.py
git commit -m "docs: explain safe 9Router operation"
```

### Task 7: Release gates and live-test boundary

**Files:**
- Modify only if a gate exposes a defect in V1.0.14 scope.

- [ ] **Step 1: Verify the frozen boundary**

Run: `git diff origin/master -- core router`

Expected: empty output.

- [ ] **Step 2: Run targeted tests**

Run: `python -m pytest tests/test_nine_router_config.py tests/test_nine_router_provider.py tests/test_cli_provider_selection.py tests/test_provider_contract.py tests/test_mcp_contract.py tests/test_packaging.py tests/test_explain_route.py -q`

Expected: all pass.

- [ ] **Step 3: Run the full non-live gate**

Run: `$env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'; python -m pytest -q -m "not live"`

Expected: no regression from V1.0.13's `1113 passed, 1 skipped, 3 deselected`, plus the new tests.

- [ ] **Step 4: Verify a clean wheel**

Build a wheel, install `"<wheel>[mcp]"` into a new venv, change to a directory outside the checkout, and assert imports for `providers.nine_router`, canonical CLI registry inclusion, and MCP metadata-only listing.

- [ ] **Step 5: Stop at the live boundary if 9Router is not running**

Live approval requires a pinned 9Router version, a dedicated non-production key or explicit loopback no-auth mode, one approved low-cost/self-hosted model, and no secrets in logs. If `127.0.0.1:20128` is not listening, record **mock and packaging verified; live execution not verified** and do not claim completion.

- [ ] **Step 6: Promote the ADR only after review**

Change ADR status from `Proposed` to `Accepted` only after code review confirms URL/auth/redirect/proxy/error-redaction/manual-only behavior and the live boundary is reported truthfully.

## Self-review

- Spec coverage: explicit enable/model/auth, TLS and URL rules, proxy bypass, redirect denial, Token Saver default-off, honest health, manual-only routing, registry parity, packaging, docs, rollback, and live boundary are all mapped to tasks.
- Placeholder scan: no implementation step relies on TODO/TBD or an unspecified error policy.
- Type consistency: `NineRouterConfig`, `NineRouterBridge`, `NineRouterProvider`, `mark_explicit_selection`, and the canonical registry names are consistent across tasks.
- Scope: no `core/`, `router/`, Multi-Agent Loop, 9Router database/account, or upstream source changes are authorized.
