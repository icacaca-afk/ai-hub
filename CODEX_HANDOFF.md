# ai-hub — Handoff to Codex

> **For**: Codex (or any AI agent taking over this project)
> **From**: The prompt engineer agent
> **Date**: 2026-08-13
> **Current version**: V1.0.11 (tag `v1.0.11`, commit `7f3f370`)
> **Test baseline**: 602 tests passing (557 regression + 45 new)
> **Repo**: https://github.com/icacaca-afk/ai-hub

---

## Step 1: Set up your environment

```bash
# Clone the repo
git clone https://github.com/icacaca-afk/ai-hub.git
cd ai-hub

# Install dependencies
pip install -e .  # or: pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -x -q
```

**GitHub token** (for API access — **do NOT commit tokens to the repo**; GitHub Push Protection blocks it):
- Retrieve from Windows Credential Manager: `git credential fill` (host=github.com) — the `password` field is the token
- Or set env var: `$env:GH_TOKEN = "<token>"` / `export GH_TOKEN=...`
- Auth header: `Authorization: token $env:GH_TOKEN`
- Base URL: `https://api.github.com`

**Pytest tips**:
- `python -m pytest tests/ -x -q` — stop on first failure
- Live/benchmark tests may hang in CI: use `--deselect "test_benchmark.py" --deselect "test_cli_plan_json.py"` to skip
- 602 tests should pass in ~2s

---

## Step 2: Read these files first (in order)

1. **`docs/ARCHITECTURE.md`** — Architecture overview, V1.0 achievement criteria, frozen boundaries
2. **`docs/adr/0032-pipeline-introspection.md`** — Most recent work, Pipeline Introspection (V1.0.11)
3. **`docs/adr/0033-predicate-api.md`** — Next ADR (V1.0.12), **already written, not committed yet**. Read it; it contains the full design for the next feature.
4. **`HANDOFF_TO_TRAE.md`** — Historical context (some parts outdated, but the Frozen Boundary section is still accurate)

**Do not modify these frozen files** (highest priority constraint, ADR-0008):

| Path | Reason |
|------|--------|
| `core/` (all) | Core Freeze (ADR-0008) |
| `router/router.py` | Base Router |
| `router/health_router.py` | V0.7 Health-aware Router |
| `router/score_router.py` | V0.8 Score Router |
| `providers/` (all) | All Provider implementations |

New code goes in: `planner/`, new `router/*.py` subclasses, new `providers/<name>/`.

---

## Step 3: The product (what is ai-hub?)

**One sentence**: ai-hub is a multi-AI Provider aggregator + intelligent router + workflow orchestrator — a command-line AI runtime that automatically picks the best free AI platform to execute a task.

**Core philosophy**:
> AI Hub does NOT unify AI models. AI Hub unifies **execution**.
> `Task → Capability → Provider → Bridge → Runtime → Result`

**Who uses it**: Individual developers who have multiple AI tools (QODER, Gemini CLI, ChatGPT, Claude CLI, QClaw, etc.) and want one unified interface.

---

## Step 4: Tasks to complete (in priority order)

### Task A — Open PR #3: "Add Claude CLI Provider" (review & merge)

**URL**: https://github.com/icacaca-afk/ai-hub/pull/3
**Author**: `surajthedev` (external contributor)
**Status**: Open, changes requested by `icacaca-afk`

A detailed review was already submitted (status: CHANGES_REQUESTED). Check if the author has responded or pushed fixes.

**What was requested** (see the review for full details):

1. **ADR number conflict**: PR uses `0007` — that number is taken by `0007-marvis-integration-via-mcp.md`. Rename the ADR to **`0036`** (update filename and title inside the doc).
2. **`health()` return type**: Must return `HealthReport` (4-state: healthy/degraded/unavailable/unknown), not `bool`. See `providers/gemini/provider.py` or `providers/qoder/provider.py` for the current pattern.
3. **Add `health_type="cli"`** to `ProviderMetadata`.
4. **Rebase onto current `master`** — the PR base is ~30 versions behind.
5. **Add contract test coverage**: Add `test_claude_provider_contract` in `tests/test_provider_contract.py` and add `ClaudeCLIProvider` to `test_capability_metadata_consistency`.

When the author responds/fixes, verify all 5 points, run the contract tests, then **merge** (squash or rebase-merge recommended for external contributions).

**API for PR reviews/comments**:
```python
# Post review comment
POST https://api.github.com/repos/icacaca-afk/ai-hub/pulls/3/reviews
{"body": "...", "event": "APPROVE"}  # or "REQUEST_CHANGES"

# Post PR comment
POST https://api.github.com/repos/icacaca-afk/ai-hub/issues/3/comments
{"body": "..."}

# Check PR status
GET https://api.github.com/repos/icacaca-afk/ai-hub/pulls/3
```

---

### Task B — Complete V1.0.12: ADR-0033 Predicate API

**ADR file**: `docs/adr/0033-predicate-api.md` — **already written, not committed yet**. Read it fully before starting.

**Summary of the feature**: Fill the observability gap left by V1.0.11. Consumers can see "there is a ConditionStage" but not "what it is evaluating". V1.0.12 introduces `PredicateDescriptor` (name/description/subject) and `ConditionStage.describe_predicate()` — the semantics come from explicit user declarations, **NOT** from introspecting the callable's source code (this is a hard constraint: no `inspect.getsource`, no AST parsing, no lambda introspection).

**Implementation steps** (from the ADR's §6):

1. Create `planner/predicate_descriptor.py` — `PredicateDescriptor` frozen dataclass
2. Add `serialize_predicate()` to `planner/metadata_serialization.py` + update `__all__`
3. In `planner/stages/condition_stage.py` — add 3 optional constructor params (`predicate_name`, `predicate_description`, `predicate_subject`) + `describe_predicate()` method
4. Export `PredicateDescriptor` from `planner/stages/__init__.py`
5. Create `tests/test_predicate_api.py` (22 tests)
6. Run full regression: `python -m pytest tests/ -x -q --deselect "test_benchmark.py" --deselect "test_cli_plan_json.py"` → must pass
7. **Commit** → tag `v1.0.12` → push
8. **ChatGPT code review**: Send to ChatGPT via Playwright CDP (Chrome with `--user-data-dir=C:\Temp\chrome-debug --remote-debugging-port=9222`). See `chatgpt-review` skill at `~/.qclaw/skills/chatgpt-review/SKILL.md`. Scripts for sending/receiving are in the workspace root.

**Hard的红线 (红线 = red lines, do NOT cross)**:
- ❌ No `inspect.getsource` / `inspect.getsourcelines`
- ❌ No AST parsing (`ast.parse`, `ast.walk`)
- ❌ No `dis.disassemble`
- ❌ No lambda introspection
- ❌ No predicate expression engine (parser, DSL, dynamic predicate editor)
- ❌ Do NOT embed predicate into `serialize_pipeline()` schema (that decision is deferred to V1.0.13)

---

### Task C — Complete V1.0.13: ADR-0034 CLI Introspection

After V1.0.12 is done. This is the CLI layer that exposes `pipeline.describe()` / `describe_predicate()` / `to_json()` as CLI commands (e.g., `ai-hub pipeline inspect`).

The ADR does not exist yet — you need to write it first (follow the ADR template in `docs/adr/TEMPLATE.md`), then implement. ChatGPT's V1.0.11 review suggested this as the natural third step in the V1.0.12 → V1.0.13 sequence.

Key decision to make in the ADR: whether to join `pipeline.describe()` with `describe_predicate()` at the CLI layer (joining the structure and the semantics), or keep them separate.

---

### Task D — Update outdated documentation

Several docs are badly outdated and should be refreshed:

| File | Current status | Action |
|------|---------------|--------|
| `README.md` | Stuck at V0.5.0-alpha | Update to reflect V1.0.11 |
| `docs/ROADMAP.md` | Stuck at V0.5 | Update |
| `HANDOFF_TO_TRAE.md` | Stuck at V0.8.2 | Replace with this document or update |
| `docs/adr/0033-predicate-api.md` | Written but not committed | Commit as part of Task B |
| `docs/adr/0035-digital-asset-sop-position.md` | Unknown, not committed | Investigate and handle |
| `docs/AI-Agent-Digital-Asset-SOP-v1.0.md` | Not committed | Investigate |
| `docs/ARCHITECTURE.md` | Modified (not committed) | Review changes |

Do **not** modify the frozen core/router/providers files even if docs reference outdated APIs there.

---

### Task E — Uncommitted workspace files

These files exist in the workspace but are not committed. Investigate and handle:

| File | Action |
|------|--------|
| `PROJECT_STATUS.md` | Keep (useful) — commit or discard |
| `v1.0.10_metadata_serialization_impl_20260721.md` | Archive artifact — commit or discard |
| `docs/AI-Agent-Digital-Asset-SOP-v1.0.md` | Investigate relevance — commit or discard |
| `v1.0.12_adr0033_predicate_api_20260813.md` | This task's artifact — commit or discard |
| `ai-hub_pr3_claude_cli_assessment_20260813.md` | Task A artifact — commit or discard |
| `docs/adr/0033-predicate-api.md` | **Core deliverable — commit as part of Task B** |
| `docs/ARCHITECTURE.md` | Review diff, commit if appropriate |

---

## Step 5: The fixed development workflow (never skip)

Every version follows this exact cycle:

```
1. Write ADR (Proposed status)
2. Send ADR to ChatGPT for review (Playwright CDP → Chrome 9222)
3. Revise ADR based on feedback
4. Implement code
5. Write tests (must pass)
6. Run full regression (602+ tests)
7. Commit (with meaningful message: "V1.0.X: <description>")
8. Tag: git tag v1.0.X && git push --tags
9. Send code to ChatGPT for review (Playwright CDP)
10. If approved: done. If not: fix and repeat from step 5.
```

**ChatGPT review scripts** (workspace root, Node.js with Playwright):
```
chatgpt_review_v1011.js     # V1.0.11 code review (reference)
chatgpt_wait2.js            # Robust polling for new replies
chatgpt_cdp.js / chatgpt_send.js / chatgpt_get_reply.js  # Generic helpers
```
Run with: `node chatgpt_review_v1011.js` (after starting Chrome with `--user-data-dir=C:\Temp\chrome-debug --remote-debugging-port=9222`).

NODE_PATH: `C:\Users\Administrator\AppData\Roaming\QClaw\npm-global\node_modules\@playwright\cli\node_modules`

---

## Step 6: Current repository state

```
HEAD:       7f3f370 V1.0.11: ChatGPT code review 9.8/10 Approved
Tag:        v1.0.11 → 4e91759
Uncommitted:
  M  docs/ARCHITECTURE.md
  ?? PROJECT_STATUS.md
  ?? docs/AI-Agent-Digital-Asset-SOP-v1.0.md
  ?? docs/adr/0033-predicate-api.md       ← Task B core deliverable
  ?? docs/adr/0035-digital-asset-sop-position.md
  ?? v1.0.10_metadata_serialization_impl_20260721.md
```

GitHub PRs waiting:
- **PR #3** "Add Claude CLI Provider" — changes requested, waiting for author (`surajthedev`)

GitHub Issues:
- **Issue #1** `[Good First Issue] Add Claude CLI Provider` — **assigned to `surajthedev`**; closed by PR #3 after merge

---

## Step 7: Key project conventions

**ADR convention**: Decisions are documented in `docs/adr/00XX-feature-name.md`. Status values: `Proposed` → `Accepted` → (never deprecated unless superseded).

**Version tag convention**: `v{major}.{minor}.{patch}` (e.g., `v1.0.12`). All lower-case `v` prefix.

**Commit message convention**: `V{major}.{minor}.{x}: <short description>`. ChatGPT review record commit: `V{major}.{minor}.{x}: ChatGPT code review {score}/10 Approved`.

**Test file naming**: `tests/test_<feature>.py` for new features. Use `@pytest.mark.live` to mark tests that hit live providers (excluded by default in CI).

**No direct `exec` calls in code for provider communication** — use the Provider/Bridge abstraction. Do not call `subprocess` directly outside of Bridge implementations.

**PowerShell notes**: On Windows, some CLI tests may show GBK encoding artifacts in subprocess output. This is a known environment issue, not a code bug. Tests should still pass.

---

## When you are done

Update this document to mark completed tasks. If you find issues or make discoveries, document them here so the next agent can pick up where you left off.
