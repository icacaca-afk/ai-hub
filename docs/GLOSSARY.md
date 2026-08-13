# AI Hub — Glossary

[English](GLOSSARY.md) | [简体中文](GLOSSARY.zh-CN.md)

> Canonical terminology for maintained documentation at V1.0.11.

| Term | Definition | Primary location |
|---|---|---|
| Task | A user's single requested unit of work, including content, capabilities, context, and artifacts. | `core/task.py` |
| Capability | A namespaced label such as `code.generate` used to match tasks to providers. | `core/capabilities.py` |
| Provider | A declaration of capabilities and routing metadata that selects a Bridge. It does not own transport details. | `core/provider.py` |
| Bridge | The communication boundary for a CLI process, HTTP API, browser, GUI, or test runtime. It returns `BridgeResult`. | `core/bridge.py` |
| Runtime | The external tool or service that actually performs work. | External entity |
| Result | The unified user-facing execution outcome. | `core/result.py` |
| CapabilityRegistry | The provider registry and Capability-to-Provider lookup. | `core/registry.py` |
| Router | Selects a Provider for a Task; specialized routers may include health or score signals. | `router/` |
| HealthReport | A four-state provider observation: healthy, degraded, unknown, or unavailable. | `core/health.py` |
| Plan | An ordered collection of Steps produced by a Planner. | `planner/plan.py` |
| Step | One independently routed unit inside a Plan. | `planner/plan.py` |
| ExecutionPipeline | Composes pre- and post-execution stages around the Bridge boundary. | `planner/pipeline.py` |
| ExecutionContext | Immutable-style data passed between pipeline stages. | `planner/pipeline.py` |
| ExecutionStage | A callable pipeline unit such as RetryStage, CheckpointStage, or ConditionStage. | `planner/stages/` |
| ExecutionEvent | An immutable execution fact used by trace, persistence, and statistics consumers. | `planner/execution_event.py` |
| StageDescriptor | Static identity and capability metadata for a stage. | `planner/stage_descriptor.py` |
| RuntimeMetadata | Structured runtime metadata produced during pipeline execution. | `planner/runtime_metadata.py` |
| StageRegistry | Registration and discovery of stage descriptors and factories. | `planner/stage_registry.py` |
| PipelineDescriptor | A side-effect-free structural description of a pipeline, including stable node IDs and edges. | `planner/pipeline_descriptor.py` |
| PredicateDescriptor | V1.0.12 explicit semantic metadata for a ConditionStage predicate. | `planner/predicate_descriptor.py` |
| ADR | An immutable Architecture Decision Record under `docs/adr/`. | `docs/adr/` |

## Canonical relationships

```text
Task → Capability → Provider → Bridge → Runtime → Result

Plan → Step → ExecutionPipeline → ExecutionEvent
                     │
                     └──► RuntimeMetadata / descriptors / serialization
```

Do not redefine these terms in other maintained documents; link here when a
definition is needed.
