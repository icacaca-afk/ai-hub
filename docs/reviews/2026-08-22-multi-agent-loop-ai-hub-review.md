# AI Hub × multi-agent-loop Review and Trae Dispatch

Date: 2026-08-22 (Asia/Shanghai)

## Review conclusion

`multi-agent-loop` is useful as an optional orchestration and governance layer
above AI Hub. It should not replace the existing Provider/Bridge/Router path or
force simple `ask` and `plan` commands through a state machine.

The recommended integration boundary is:

```text
RunController / bounded loop
        ↓
AI Hub Planner + ExecutionPipeline
        ↓
Router → Provider → Bridge
```

The first useful slice is a V1.1 RunController with explicit states, bounded
revision loops, structured evidence, approval gates, and resume support. It
should reuse AI Hub's existing Planner, ExecutionEvent, SQLiteExecutionStore,
and pipeline inspection APIs. It must not modify the frozen Core, base Routers,
or existing Provider implementations.

Immediate release work remains higher priority: reconcile and publish the local
V1.0.12/V1.0.13 commits before starting the V1.1 loop.

## Trae Provider integration

Added `TraeCLIProvider` using the existing `CLIBridge` boundary. It supports
explicit `--provider trae_cli` selection and uses `trae-cli doctor` as a
non-destructive readiness check. This catches a missing effective model before
the task is executed.

## Dispatch task

The following task was prepared for Trae Work. It is intentionally read-only:

> Audit the `multi-agent-loop` reference and AI Hub integration plan in this
> worktree. Do not edit files, run mutating commands, create commits, push
> branches, or send external messages. Inspect the current Planner, Pipeline,
> EventBus, SQLite execution store, CLI provider-selection path, ADRs, and
> roadmap. Return: (1) architecture risks, (2) the smallest V1.1 RunController
> design, (3) state transitions and invariants, (4) evidence and approval
> artifact schemas, (5) a bounded implementation plan with tests, and (6) a
> release-blocker list. Prefer reuse over duplicate state/event/storage
> systems. Explicitly preserve the frozen Core/Router/Provider boundaries.

## Dispatch evidence

AI Hub routing was attempted with:

```powershell
python -m cli.main ask "<read-only multi-agent-loop audit prompt>" --provider trae_cli
```

Routing selected `Trae CLI` with score `98.0`, but execution was correctly
blocked before model invocation because Trae Work has no effective model
configured. Direct Trae diagnostics reported:

```text
trae-cli version 0.120.40
model: no effective model configured
fix: set `model.name` in your config, or use `/model` to pick one
```

AI Hub therefore returned `No available provider` after the readiness check.
No files were changed by Trae and no external task was executed.

## Next action

Configure a valid `model.name` in Trae Work, rerun the same AI Hub-pinned audit,
save the response as review evidence, and manually review it before accepting
any implementation changes.
