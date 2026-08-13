# AI Hub — Product Overview

[English](PRODUCT.md) | [简体中文](PRODUCT.zh-CN.md)

> Product direction at repository milestone V1.0.11

## One-sentence definition

AI Hub is a local-first execution runtime that accepts one task, selects an
appropriate available AI provider, and returns a consistent result.

## The problem

Developers often use several AI tools: local CLIs, hosted APIs, browser
products, and workflow systems. Each tool has a different command, login model,
quota, health state, and output shape. Users spend time selecting and switching
tools instead of completing the task.

## Product promise

```text
One task in → capability-aware execution → one result out
```

AI Hub should:

- prefer providers that satisfy the task's capabilities;
- expose why a provider was selected;
- account for availability, quota, latency, and priority;
- support both single-step and planned multi-step execution;
- preserve execution facts for diagnosis and statistics;
- keep external runtime details behind Bridge implementations.

## Primary users

- Individual developers and technical independent workers
- People who already use multiple AI CLIs or APIs
- Cost- and quota-aware users who still need predictable execution
- Contributors adding runtime adapters without redesigning the router

Enterprise identity, organization-wide policy, billing, and SLA management are
not current product goals.

## Current product surface

| Need | Product capability |
|---|---|
| Execute one request | `ai-hub ask` |
| Break down a larger request | `ai-hub plan` |
| Understand routing | `ai-hub explain-route` |
| Diagnose provider readiness | `ai-hub status`, `doctor`, `benchmark` |
| Inspect execution | `inspect`, `trace`, `exec-history`, `stats` |
| Compose workflow behavior | ExecutionPipeline stages and hooks |
| Inspect pipeline structure | `describe()`, `to_dict()`, `to_json()` API |

## Product principles

1. Unify execution, not models.
2. Treat Task and execution facts as first-class data.
3. Route by capability before provider identity.
4. Prefer explicit metadata over source-code inference.
5. Keep provider communication behind Bridge boundaries.
6. Preserve frozen contracts and add behavior at extension points.

## Success measures

- A new user can install the project and inspect available providers in ten
  minutes or less.
- A routing decision is explainable from explicit health, capability, priority,
  latency, and quota signals.
- Workflow features do not require changes to frozen Core or base Router APIs.
- Reader-facing documentation stays synchronized in English and Simplified
  Chinese.
- Release tests and contract tests remain reproducible without mandatory live
  provider access.

See the [Roadmap](ROADMAP.md) for planned milestones and the
[Architecture Overview](ARCHITECTURE.md) for technical boundaries.
