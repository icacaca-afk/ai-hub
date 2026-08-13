# AI Hub

> One task. Any AI. Any runtime.

[English](README.md) | [简体中文](README.zh-CN.md)

AI Hub is a local-first AI runtime that routes tasks by capability, selects an
available provider, executes through a bridge, and returns a consistent result.
It unifies execution across CLI tools, HTTP APIs, browser runtimes, and test
providers; it does not attempt to make every model look identical.

```text
Task → Capability → Provider → Bridge → Runtime → Result
```

## Project status

- Latest repository release: **V1.0.11** (`v1.0.11`)
- Current milestone: Pipeline Introspection, described by
  [ADR-0032](docs/adr/0032-pipeline-introspection.md)
- V1.0.12 Predicate API is implemented locally and awaiting release review; see
  [ADR-0033](docs/adr/0033-predicate-api.md)
- V1.0.11 verification baseline: **602 passing tests** at release time
- Stability boundary: `core/`, `router/router.py`,
  `router/health_router.py`, `router/score_router.py`, and existing provider
  implementations are frozen except for bug fixes

The package metadata in `pyproject.toml` still reports `0.0.1`; until that is
aligned with repository tags, treat Git tags and ADR milestones as the release
source of truth.

## What it provides

- Capability-based provider routing with health, priority, latency, and quota
  signals
- A shared Provider/Bridge boundary for CLI, API, browser, MCP, and test
  runtimes
- Rule-based and LLM-assisted multi-step planning
- An execution pipeline with retry, checkpoint, condition, and hook stages
- Execution events, in-memory traces, SQLite history, and statistics
- Metadata registries and deterministic serialization
- Side-effect-free pipeline structure inspection through
  `ExecutionPipeline.describe()`, `to_dict()`, and `to_json()`

## Quick start

Requirements: Python 3.11 or later. Individual providers may require their own
CLI, API key, or login.

```bash
git clone https://github.com/icacaca-afk/ai-hub.git
cd ai-hub
python -m pip install -e .

ai-hub status
ai-hub caps
ai-hub ask "Write a Python HTTP server"
ai-hub plan "Analyze a CSV file and summarize the findings"
```

Run the test suite without live-provider requirements:

```bash
python -m pytest tests/ -x -q \
  --deselect "tests/test_benchmark.py" \
  --deselect "tests/test_cli_plan_json.py"
```

Some tests exercise installed external runtimes. Use the repository's pytest
markers and test documentation when you need a fully isolated run.

## Main commands

| Command | Purpose |
|---|---|
| `ai-hub ask "<task>"` | Route and execute a single task |
| `ai-hub plan "<task>"` | Decompose and execute a multi-step task |
| `ai-hub explain-route "<task>"` | Explain provider selection |
| `ai-hub status` / `doctor` | Inspect and diagnose providers |
| `ai-hub benchmark` | Measure healthy provider latency and success |
| `ai-hub inspect` / `trace` | Inspect plans and execution timelines |
| `ai-hub exec-history` / `stats` | Query persisted execution history |
| `ai-hub quota` / `caps` | Show quota and capability information |
| `ai-hub session` | Manage runtime sessions |

## Architecture

```text
CLI / MCP Client
        │
        ▼
Task ──► Planner / Router
        │
        ▼
ExecutionPipeline
  pre-stages → Provider Bridge → post-stages
        │
        ├──► ExecutionEvent → Trace / SQLite / Statistics
        └──► Result
```

The architectural invariant is that a Provider declares capabilities and
selects a Bridge; the Bridge owns communication with the external runtime.
Workflow concerns belong in `planner/` and the execution pipeline, not in the
frozen Router or Provider contracts.

Read the [Architecture Overview](docs/ARCHITECTURE.md) for component boundaries,
runtime flow, and the document map.

## Adding a provider

New providers live in `providers/<name>/` and implement the existing Provider
contract. They declare `ProviderMetadata`, select a Bridge, and expose health,
authentication, and quota state. Do not modify the base Router to recognize a
provider.

See the [Provider Specification](docs/PROVIDER_SPEC.md) and
[Contributing Guide](CONTRIBUTING.md) before opening a change. Existing provider
implementations are frozen; a genuinely new provider may be added in its own
directory.

## Documentation

Reader-facing, maintained documentation is published in English and Simplified
Chinese. The unsuffixed filename is English; `.zh-CN.md` is Chinese. ADRs,
external reviews, historical handoffs, and version-specific artifacts remain in
their original language because they are immutable records.

- [Documentation index](docs/README.md) · [中文文档索引](docs/README.zh-CN.md)
- [Roadmap](docs/ROADMAP.md) · [路线图](docs/ROADMAP.zh-CN.md)
- [Product](docs/PRODUCT.md) · [产品说明](docs/PRODUCT.zh-CN.md)
- [Glossary](docs/GLOSSARY.md) · [术语表](docs/GLOSSARY.zh-CN.md)
- [Provider Specification](docs/PROVIDER_SPEC.md) ·
  [Provider 规范](docs/PROVIDER_SPEC.zh-CN.md)
- [Contributing](CONTRIBUTING.md) · [贡献指南](CONTRIBUTING.zh-CN.md)

## License

[MIT](LICENSE)
