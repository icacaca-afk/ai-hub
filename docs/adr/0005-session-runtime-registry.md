# ADR-0005: Session / RuntimeRegistry (V0.3)

Date: 2026-07-12
Status: Accepted

## Context

V0.2 (QuotaManager) closed. V0.3 adds Session lifecycle management.

Users need cross-Task context: a CLI session that remembers prior outputs, an API conversation that preserves message history, a GUI automation session that keeps window state. Without Session, each Task is stateless.

## Decision

Two new modules, zero changes to Router/Provider/Bridge:

### Session (`core/session.py`)
- Dataclass: `session_id, provider_name, created_at, updated_at, status, context`
- Status lifecycle: `active → checkpointed → active → ... → destroyed`
- `SessionManager` handles create/get/list/checkpoint/resume/destroy
- Persisted as JSON (`~/.ai-hub/sessions.json`)

### RuntimeRegistry (`core/runtime_registry.py`)
- Maps `session_id → Bridge` (in-memory)
- `bind() / get_bridge() / unbind() / active_sessions() / count() / clear()`
- Session.destroy() triggers unbind() (caller responsibility, not automatic)

## What We Did NOT Do

- ❌ No Scheduler (reset is just an interface)
- ❌ No Agent / Prompt management / Memory / RAG / Workflow
- ❌ No GUIBridge (V0.4)
- ❌ No BrowserBridge (V0.5)
- ❌ No new Provider
- ❌ No Router modification
- ❌ No Provider modification
- ❌ No Bridge base class modification

## Consequences

- Session is optional: Router works without it (current behavior unchanged)
- Bridge implementations can optionally use Session for stateful operations
- RuntimeRegistry is in-memory only (no persistence needed; Bridge handles its own state)
- Future GUIBridge will use Session to track window/process state across Tasks
