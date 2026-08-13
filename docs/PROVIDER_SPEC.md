# AI Hub — Provider Specification

[English](PROVIDER_SPEC.md) | [简体中文](PROVIDER_SPEC.zh-CN.md)

> Provider contract: stable · Health observation: V0.6+ · Updated for V1.0.11

## Responsibility boundary

A Provider declares identity, capabilities, routing preferences, and a Bridge.
The Bridge owns communication with the external Runtime.

```text
Task → Provider.select_bridge(Task) → Bridge.run(Task) → BridgeResult → Result
```

A Provider must not implement its own `execute()` transport path. Do not add
provider-specific branches to the base Router.

## Required declaration

```python
from core.bridge import CLIBridge
from core.health import HealthReport
from core.provider import Provider, ProviderMetadata


class YourProvider(Provider):
    metadata = ProviderMetadata(
        name="your_platform",
        display_name="Your Platform",
        description="Short runtime description",
        version="0.1.0",
        capabilities=["code.generate", "text.summarize"],
        priority=80,
        fallback=["demo"],
        quota_type="unknown",
        quota_total=-1,
        health_type="cli",
    )

    bridge = CLIBridge(
        command="your-cli",
        version_command="your-cli --version",
        command_template='your-cli "{task}"',
    )

    def health(self) -> HealthReport:
        if self.bridge.check_available():
            return HealthReport.healthy(
                self.name,
                authenticated=self.authenticated(),
                quota_ok=self.quota_left() != 0,
            )
        return HealthReport.unavailable(
            self.name,
            message="your-cli is not installed or not on PATH",
        )

    def authenticated(self) -> bool:
        return self.bridge.check_available()

    def quota_left(self) -> int:
        return -1
```

Existing legacy providers may still return `bool` from `health()` because the
Health Framework normalizes that result. New providers should return
`HealthReport` so callers retain the healthy/degraded/unknown/unavailable state
and diagnostic message.

## ProviderMetadata

| Field | Type | Meaning |
|---|---|---|
| `name` | `str` | Stable unique identifier |
| `display_name` | `str` | Human-readable name |
| `description` | `str` | Short adapter description |
| `version` | `str` | Adapter version |
| `capabilities` | `list[str]` | Registered Capability labels |
| `priority` | `int` | Static routing priority; larger wins |
| `fallback` | `list[str]` | Provider name fallback order |
| `quota_type` | `str` | `daily`, `monthly`, `unlimited`, or `unknown` |
| `quota_total` | `int` | Declared total; `-1` means unlimited/unknown |
| `quota_auto_detect` | `bool` | Whether quota can be detected automatically |
| `health_type` | `str` | `cli`, `api`, `browser`, `mcp`, or empty fallback |
| `cost_currency` | `str \| None` | Optional cost currency |
| `cost_amount` | `float` | Optional cost amount |
| `cost_unit` | `str` | Cost unit, normally `per_call` |
| `timeout` | `int` | Per-call timeout in seconds |
| `retry_count` | `int` | Provider-level retry count |
| `retry_delay` | `float` | Delay between provider retries |

## Required behavior

- `select_bridge(task)` returns a Bridge. The inherited implementation is
  sufficient when the Provider has one class-level `bridge`.
- `authenticated()` returns a Boolean observation without prompting the user.
- `quota_left()` returns `0` when unavailable due to quota and `-1` when no
  numeric limit is known.
- `health()` should be bounded, diagnostic, and safe to call from `status` or
  routing health checks.
- Every declared capability must exist in `core.capabilities.CAPABILITIES`.

## Bridge contract

```python
class Bridge(ABC):
    def run(self, task: Task, **kwargs) -> BridgeResult: ...
    def check_available(self) -> bool: ...
```

`BridgeResult` contains `success`, `output`, `error`, `duration_ms`, `artifacts`,
and `raw`. It does not contain a Provider field.

Use an existing Bridge where possible. Adding a new transport abstraction or
changing `core/bridge.py` crosses the frozen Core boundary and requires an ADR.
Provider communication must not invoke a parallel transport path outside a
Bridge implementation.

## Integration and tests

1. Create `providers/<name>/__init__.py` and `provider.py`.
2. Export the Provider class from the package.
3. Register it in the runtime registry construction path if automatic CLI
   discovery is not yet available.
4. Add a provider contract test in `tests/test_provider_contract.py`.
5. Add the class to `test_capability_metadata_consistency`.
6. Add focused health/authentication tests that do not require the real runtime.
7. Run the provider contract test, then the full non-live regression suite.

Changes to existing Provider implementations remain frozen except for justified
bug fixes. A new Provider belongs in a new directory and must not modify Core or
base Router behavior.
