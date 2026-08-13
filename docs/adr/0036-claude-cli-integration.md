# ADR-0036: Claude CLI Provider Integration

- **Status**: Accepted
- **Date**: 2026-07-13
- **Milestone**: V0.1.1
- **Related Provider**: claude_cli (Claude Code CLI)

## Background

CLIBridge has already been validated through two real providers (Gemini CLI and
QODER CLI). This ADR adds a third real CLI provider (Claude Code CLI), further
validating CLIBridge stability across different authentication styles
(environment variable vs. OAuth login).

## Command Format

Claude Code CLI print mode (non-interactive):
```bash
claude -p "{task}"
```

- Command: `claude`
- Authentication: `ANTHROPIC_API_KEY` environment variable, or a completed
  `claude login` OAuth session (token cached by the CLI)
- Docs: https://docs.claude.com/claude-code

## New Requirements Exposed

None. CLIBridge's existing `command_template` and `env` parameters fully cover
Claude CLI's requirements, identical to the Gemini CLI integration pattern.

## Interface Changes

| Change | Type | Backward Compatible | Scope |
|--------|------|---------------------|-------|
| None   | —    | —                   | —     |

## Architecture Verification

| Core Module         | Modified | Reason                                   |
|---------------------|----------|------------------------------------------|
| `core/provider.py`  | No       | —                                        |
| `core/registry.py`  | No       | —                                        |
| `core/result.py`    | No       | —                                        |
| `core/task.py`      | No       | —                                        |
| `core/capabilities.py` | No    | All capability tags already registered   |
| `router/router.py`  | No       | —                                        |
| `core/bridge.py`    | No       | CLIBridge command_template + env suffice |

> Zero modifications to core/ + bridge.py.

## Decisions

1. `health()` returns a `HealthReport` object following the V0.6 Health
   Framework (ADR-0009+). Returns `HealthReport.healthy(...)` when the `claude`
   binary is found in PATH, `HealthReport.unavailable(...)` otherwise.
2. `metadata.health_type` is set to `"cli"` as required for CLI providers.
3. `authenticated()` checks `ANTHROPIC_API_KEY` at call time (not at import
   time) so that environment changes take effect without a restart. Falls back
   to assuming authenticated if the CLI is available (OAuth login path).
4. `command_template` uses `claude -p "{task}"` format, consistent with the
   Gemini CLI `-p` argument style.
5. Provider priority is 85 (between QODER at 100 and Gemini at 80); fallback
   chain is `gemini_cli -> demo`.

## Lessons Learned

- Reading `ANTHROPIC_API_KEY` at call time rather than at module import is a
  low-cost improvement that avoids requiring a process restart when the key
  changes in the environment.
- CLIBridge's `env` parameter is general enough to handle both
  environment-variable and OAuth authentication modes without any bridge
  modifications.
- Different CLI tools have distinct authentication styles (Gemini uses an env
  var, QODER uses browser login, Claude supports both). Keeping `authenticated()`
  in each Provider continues to be the right design choice.
