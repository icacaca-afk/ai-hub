# AI Hub — Architecture Overview

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE.zh-CN.md)

> Repository milestone: V1.0.11 · Status: maintained overview · Updated: 2026-08-13

## Purpose

This document is the entry point to AI Hub's architecture. Normative details
live in the Runtime Contract, Provider Specification, and accepted ADRs.

## System identity

AI Hub is an AI runtime, not only a model gateway. A task is the first-class
input; capabilities determine eligible providers; providers select bridges;
bridges communicate with external runtimes.

```text
Task → Capability → Provider → Bridge → Runtime → Result
```

The system unifies execution, not model semantics.

## Static architecture

```text
┌──────────────────────────────────────────────────────────┐
│ CLI / MCP adapters                                      │
│ ask · plan · inspect · trace · history · stats          │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│ Planner and routing                                     │
│ RuleBasedPlanner / LLMPlanner · ScoreRouter             │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│ ExecutionPipeline                                       │
│ pre-stages → Bridge boundary → post-stages              │
│ retry · checkpoint · condition · hooks                  │
└──────────────┬──────────────────────────┬────────────────┘
               ▼                          ▼
┌──────────────────────────┐  ┌────────────────────────────┐
│ Provider + Bridge        │  │ ExecutionEvent consumers   │
│ CLI / API / Browser / MCP│  │ trace · SQLite · statistics│
└──────────────┬───────────┘  └────────────────────────────┘
               ▼
        External runtime
```

## Component boundaries

| Area | Responsibility | Stability |
|---|---|---|
| `core/` | Task, Result, Provider, Bridge, health, registry contracts | Frozen |
| `router/` | Capability and score-based provider selection | Base and existing routers frozen |
| `providers/` | Runtime-specific adapters | Existing implementations frozen; new providers use new directories |
| `planner/` | Plans, pipeline, stages, events, persistence, metadata | Experimental, active development |
| `cli/` | User-facing commands and presentation | Experimental |
| `adapters/` | Protocol-facing integration such as MCP | Extension boundary |

Distribution packaging is also an architecture boundary. Setuptools discovers
packages recursively only below the maintained project namespaces, and release
verification installs a non-editable wheel outside the checkout. CLI provider
pinning narrows the registry before Router construction; it does not bypass or
modify Router behavior. `cli/version.py` is the single source for both wheel
metadata and runtime inspection, and `cli/` is a regular package so unrelated
third-party `cli.py` modules cannot shadow the application entry point.

MCP discovery is observational by default: `list_providers` returns registered
metadata with availability marked `unchecked` and performs no external probe.
Availability probing is an explicit caller choice because it may launch CLI,
authentication, browser, or network checks.

The freeze is governed by [ADR-0008](adr/0008-core-freeze.md). In the current
repository it covers `core/`, `router/router.py`, `router/health_router.py`,
`router/score_router.py`, and existing Provider implementations. Bug fixes need
explicit justification; new workflow behavior belongs in `planner/`.

## Runtime flow

1. A CLI or adapter creates a `Task`.
2. A planner may decompose it into a `Plan` of `Step` objects.
3. Routing maps required capabilities to a suitable Provider.
4. `ExecutionPipeline` runs pre-stages, crosses the Provider/Bridge boundary,
   then runs post-stages.
5. Execution facts are emitted as `ExecutionEvent` objects.
6. Trace, SQLite storage, and statistics consume those events without becoming
   the execution source of truth.
7. The caller receives a unified `Result`.

## Execution pipeline

V1.0 moved workflow concerns out of Router subclasses and into composable
pipeline stages:

- V1.0.1: ExecutionPipeline
- V1.0.2: RetryStage
- V1.0.3: CheckpointStage
- V1.0.4: ConditionStage
- V1.0.5: Pipeline hooks
- V1.0.6–V1.0.10: descriptors, registries, metadata access, and serialization
- V1.0.11: PipelineDescriptor and side-effect-free pipeline introspection

The V1.0.11 introspection invariant is one-way:

```text
ExecutionPipeline
  → describe()
  → PipelineDescriptor
  → serialize_pipeline()
  → dict
  → JSON
```

`serialize_pipeline()` consumes a descriptor; it does not inspect an executable
pipeline directly.

## Observability model

`ExecutionEvent` is the immutable execution fact. In-memory traces, persisted
history, and statistics are projections over those facts. Static metadata has a
separate path through StageDescriptor, RuntimeMetadata, StageRegistry,
PipelineDescriptor, and canonical serialization functions.

This separation keeps execution, static structure, and presentation from
silently changing one another.

## Document map

| Document | Role |
|---|---|
| [Runtime Contract](runtime-contract.md) | Normative runtime behavior |
| [Provider Specification](PROVIDER_SPEC.md) | Provider and Bridge extension contract |
| [Glossary](GLOSSARY.md) | Canonical project terminology |
| [Roadmap](ROADMAP.md) | Milestones and current direction |
| [ADR directory](adr/) | Immutable architecture decisions |
| [Review directory](reviews/) | External review records |

## Governance layer

The [AI Agent Digital Asset SOP](AI-Agent-Digital-Asset-SOP-v1.0.md) is a
governance reference, not a runtime component. Its position is recorded by
[ADR-0035](adr/0035-digital-asset-sop-position.md); it does not extend the frozen
core or introduce an execution dependency.

## Next milestone

[ADR-0033](adr/0033-predicate-api.md) defines explicit predicate semantic
metadata for V1.0.12; the implementation is awaiting release review. It deliberately excludes source inspection, AST parsing,
lambda introspection, and a predicate expression engine. CLI presentation is
deferred to a later ADR.
