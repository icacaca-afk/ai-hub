# ADR-0012: Routing Decision Trace v2

## Status
Proposed (V0.8.2)

## Context

V0.8.0 ScoreRouter 的 `last_route_reason` 混用了两个维度：
- **health group**: healthy / degraded / fallback
- **routing strategy**: score / first-match / fallback

例如 `"group": "score"` 实际上是策略名，不是健康分组。

V0.7.x explain-route JSON 输出中 `"version": "v0.7.1"` 混淆了 schema 版本和运行时版本。

ChatGPT V0.8.1 审核建议：
1. 拆开 `group` → `strategy` + `reason`
2. `version` → `schema_version` + `runtime_version`

## Decision

### 1. last_route_reason 结构变更

之前：
```python
{
    "selected": "gemini_cli",
    "group": "score",
    "score": 94.7,
    "skipped": []
}
```

之后：
```python
{
    "selected": "gemini_cli",
    "strategy": "score",          # score / fallback / none
    "reason": "highest_score",    # 人类可读的原因
    "score": 94.7,
    "skipped": []
}
```

### 2. explain-route JSON 输出变更

之前：
```json
{
    "version": "v0.8",
    "task": "...",
    ...
    "decision": {
        "selected": "gemini_cli",
        "group": "score",
        "skipped": []
    }
}
```

之后：
```json
{
    "schema_version": "2",
    "runtime_version": "0.8.2",
    "task": "...",
    ...
    "decision": {
        "selected": "gemini_cli",
        "strategy": "score",
        "reason": "highest_score",
        "score": 94.7,
        "skipped": []
    }
}
```

### 3. explain-route Human 输出变更

之前：
```
Decision:
  Selected:  gemini_cli
  Group:     score
  Score:     94.7
```

之后：
```
Decision:
  Selected:  gemini_cli
  Strategy:  score
  Reason:    highest_score
  Score:     94.7
```

### 4. Benchmark 测试隔离

`test_benchmark.py` 拆成：
- **单元测试**：FakeProvider + 模拟 latency，不调用真实 Provider
- **Live 测试**：标记 `@pytest.mark.live`，需真实 Provider，CI 默认跳过

### 5. CLI ScoreRouter Integration Regression Test

新增 `tests/test_cli_score_integration.py`：
- 验证 `ai-hub ask` 经过 ScoreRouter（输出包含 `[Router] Score:`）
- 验证 `ai-hub explain-route` 输出包含 `Strategy:` 和 `score:`
- 验证 JSON 模式包含 `schema_version` 和 `runtime_version`

## Consequences

- `last_route_reason` 的 `group` key → `strategy` key（破坏性变更，但 V0.8.x 仍 Experimental）
- explain-route JSON 的 `version` → `schema_version` + `runtime_version`（破坏性变更）
- benchmark 测试不再依赖真实 Provider，CI 可安全运行
- 新增 integration test 保护 CLI 入口

## Frozen Impact

- core/ ✅ 零修改
- router/router.py ✅ 零修改
- router/health_router.py ✅ 零修改
- router/score_router.py — 修改 `last_route_reason` key 名
- providers/ ✅ 零修改
