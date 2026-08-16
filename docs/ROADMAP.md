# AI Hub — Roadmap

[English](ROADMAP.md) | [简体中文](ROADMAP.zh-CN.md)

> Current repository milestone: V1.0.11 · Updated: 2026-08-13

## Completed phases

| Phase | Outcome | Status |
|---|---|---|
| V0.0–V0.5 | Provider/Bridge runtime, quota, sessions, adapters, core freeze | Complete |
| V0.6–V0.8 | Health framework, health-aware routing, score routing | Complete |
| V0.9 | Planning, execution events, trace, SQLite history, analytics | Complete |
| V1.0.1–V1.0.5 | Pipeline, retry, checkpoint, condition, hooks | Complete |
| V1.0.6–V1.0.10 | Stage metadata, registries, access APIs, serialization | Complete |
| V1.0.11 | Pipeline introspection | Complete |

## Current sequence

| Version | Decision | Deliverable | Status |
|---|---|---|---|
| V1.0.11 | [ADR-0032](adr/0032-pipeline-introspection.md) | `PipelineDescriptor`, `describe()`, deterministic JSON | Released |
| V1.0.12 | [ADR-0033](adr/0033-predicate-api.md) | Explicit predicate semantic metadata | Implemented; review pending |
| V1.0.13 | [ADR-0034](adr/0034-cli-pipeline-introspection.md) | `ai-hub pipeline inspect [--json]` with presentation-only predicate joins | Implemented; review pending |

V1.0.12 explicitly excludes callable source inspection, AST parsing, lambda
introspection, and a predicate DSL or expression engine. V1.0.13 keeps the
canonical pipeline schema unchanged and joins predicate semantics only in the
CLI presentation document.

## Maintenance track

- Keep the frozen Core, base routers, existing score/health routers, and current
  provider implementations unchanged except for justified bug fixes.
- Maintain English and Simplified Chinese versions of reader-facing documents.
- Align package metadata with repository release tags.
- Refresh installation and provider-extension documentation against the actual
  contract tests.
- Review the external Claude CLI Provider contribution after its requested
  changes are pushed and rebased.

## Later candidates

The following ideas require their own ADR and are not commitments:

- CLI visualization of pipeline structure and predicate semantics
- Metadata schema versioning
- Restricted structured predicates, only if callable metadata proves
  insufficient
- Additional providers through the existing Provider/Bridge extension boundary
- Ecosystem packaging and plugin discovery

## Release workflow

Architecture work follows this sequence:

```text
Proposed ADR → external review → revision → implementation → focused tests
→ full regression → commit/tag → code review → approval
```

Historical intent and scores remain in the corresponding ADR and review files;
this roadmap records only the maintained direction.
