# ADR-0038: Bounded 9Router Provider Integration

- Status: Proposed
- Date: 2026-09-20
- Target: V1.0.14

## Context

9Router exposes a local OpenAI-compatible gateway with its own account selection,
model/Combo routing, protocol conversion, quota tracking, fallback, and optional
prompt/context rewriting. AI Hub already owns task capability classification,
Provider selection, execution history, and the frozen Provider → Bridge → Router
contract. Integrating the projects is useful only if their responsibilities stay
separate.

An earlier uncommitted prototype selected the first item returned by `/v1/models`,
treated loopback as authenticated, allowed automatic routing with a high priority,
and inferred full health from model discovery. Those behaviors are not acceptable
for a reproducible or security-sensitive workflow.

## Decision

Add a thin `NineRouterProvider` under `providers/nine_router/`. AI Hub remains the
only task execution entry point; 9Router remains an external downstream gateway.
No 9Router source, database, account, or protocol-conversion code is copied into
AI Hub.

### Configuration boundary

The integration is disabled unless `NINE_ROUTER_ENABLED=1`.

When enabled:

- `NINE_ROUTER_MODEL` is mandatory. It may be an exact model ID or an exact
  9Router Combo ID. AI Hub never chooses the first discovered model.
- `NINE_ROUTER_API_KEY` is mandatory unless the endpoint is loopback and
  `NINE_ROUTER_ALLOW_NO_AUTH=1` is also set.
- The default base URL is `http://127.0.0.1:20128/v1`.
- Non-loopback URLs must use HTTPS.
- URL userinfo, query, and fragment components are rejected.
- Timeout must be positive and no greater than 300 seconds.

Configuration is parsed into an immutable object before network access. Invalid
enabled configuration fails closed and does not probe the gateway.

### HTTP boundary

V1.0.14 supports only non-streaming text Chat Completions:

- `GET /v1/models` validates that the configured model/Combo exists.
- `POST /v1/chat/completions` executes one user text message with `stream=false`.
- `X-9Router-Token-Saver` is sent as `off` by default and becomes `on` only after
  an explicit configuration opt-in.
- Loopback requests bypass system HTTP and HTTPS proxies.
- Redirects are rejected, preventing Authorization forwarding to another host.
- HTTP, timeout, connection, JSON, and response-shape failures become bounded,
  redacted `BridgeResult` failures.

Tool calls, streaming, images, audio, artifacts, arbitrary request-body overrides,
Cloud Sync/Tunnel, prompt-style injection, and MITM credential reuse are outside
this version's scope.

### Routing and health boundary

The Provider is manual-only in V1.0.14. It may be executed by CLI only after an
explicit `--provider nine_router` selection. Merely enabling it does not make it
eligible for automatic routing. MCP and diagnostic surfaces may list its metadata
without probing it, but MCP does not gain an implicit 9Router execution path.

`/v1/models` does not prove that Chat Completions authentication and execution
work. Therefore:

- disabled or invalid configuration reports unavailable without network I/O;
- reachable gateway plus exact model presence reports degraded, with execution
  explicitly marked unverified;
- only a real successful execution is evidence that the configured path works;
- quota and cost remain `unknown` / `upstream_managed`, never "free" or
  "unlimited" evidence.

### Architecture boundary

- No files under `core/` or `router/` change.
- Existing Providers do not change.
- CLI and MCP reuse the canonical provider registry rather than adding new
  duplicate registration lists.
- Multi-Agent Loop Phase 3 does not change and does not depend on 9Router.
- Until the actual downstream model is persisted as immutable execution evidence,
  a transparent Combo cannot prove reviewer/implementer model independence.

## Consequences

### Positive

- AI Hub can use 9Router's approved model/account fallback without duplicating it.
- Default behavior is network-free and compatible with existing installations.
- A fixed model/Combo and default-off prompt rewriting make runs more reproducible.
- The adapter can be removed or disabled without migrating AI Hub history.

### Negative

- Model validation adds a `/models` request before execution unless a later,
  separately reviewed cache is introduced.
- Manual-only routing means MCP cannot execute 9Router in this first version.
- Gateway reachability remains weaker evidence than a live Chat Completions run.
- The frozen Router currently discards `BridgeResult.raw`, limiting downstream
  model provenance in final AI Hub results.

## Verification gates

1. Configuration, URL, authentication, proxy, redirect, header, error-redaction,
   fixed-model, health, and manual-selection tests pass against local mocks.
2. Provider contract, canonical registry, CLI, MCP metadata, and wheel packaging
   tests pass.
3. The full `not live` suite passes with no real Provider probing.
4. A clean-wheel installation imports and lists the Provider outside the checkout.
5. Live verification uses a pinned 9Router version, a dedicated test credential or
   explicit loopback no-auth mode, and an approved low-cost/self-hosted model.

The ADR remains Proposed until independent review confirms these gates. A running
local 9Router is not currently assumed.

## Rollback

Set `NINE_ROUTER_ENABLED=0` or remove the variable. The Provider immediately
becomes unavailable and network-free; existing Providers and AI Hub history remain
unchanged. 9Router accounts, Combos, configuration, and data stay in the separate
9Router installation. If an upstream release breaks compatibility, pin or roll
back 9Router without rolling back AI Hub core.
