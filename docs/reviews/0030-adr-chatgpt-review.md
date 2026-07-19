# ADR-0030 ChatGPT ADR Review Summary

- **审核目标**: V1.0.9 ADR-0030 Registry Introspection 草稿
- **审核时间**: 2026-07-19
- **审核 prompt**: `docs/reviews/0030-adr-chatgpt-review-prompt.md` (~33.7 KB)
- **审核 raw 回复**: `docs/reviews/0030-adr-chatgpt-review-raw.txt` (~10 KB)
- **总评分**: **9.62 / 10 APPROVED (minor revisions recommended)** ✅
- **状态**: Approved with 5 项 minor revisions

---

## 审核评分明细

| 维度 | 分数 |
|------|------|
| 架构方向 | 9.8 / 10 |
| API 一致性 | 9.6 / 10 |
| 向后兼容 | 9.9 / 10 |
| 数据结构 | 9.7 / 10 |
| 替代方案质量 | 9.8 / 10 |
| 测试策略 | 9.4 / 10 |
| 实施计划 | 9.8 / 10 |
| V1.0.10 演化规划 | 9.7 / 10 |
| **总分** | **9.62 / 10** |

---

## 审核结论

> ADR-0030 是一个非常符合 V1.0.x 演进节奏的 ADR。
>
> 它没有继续扩大 Registry 职责，而是准确解决 ADR-0029 留下的核心问题：
> - ADR-0029 解决 "Where is the Stage?"
> - ADR-0030 解决 "What is in the Registry and what does it need?"

**3 个架构判断全部认可**:
1. StageInfo 不进入 StageDescriptor (StageDescriptor=Stage 自身, StageInfo=Registry 上下文)
2. requires 不自动反射 (runtime dependency 是部署/组装层信息)
3. Serialization 与 Introspection 分离 (ADR-0030 Registry view, ADR-0031 通用 serialization)

---

## 8 个审核问题逐项结论

| 问题 | 结论 |
|------|------|
| Q1 StageInfo 字段 | ✅ 当前 4 字段够用, 不加 last_used_at / invocation_count (留 V1.1 RuntimeMetrics) |
| Q2 requires 字符串 | ✅ V1.x 字符串 (JSON/CLI/plugin friendly), V2 转 Enum |
| Q3 source 字符串 | ✅ 当前 3 档够用 (builtin/third_party/test), 不加 deprecated (experimental 已在 descriptor) |
| Q4 to_dict delegation | ✅ 当前 helper 正确, ADR-0031 处理通用 serialization, 不提前耦合 |
| Q5 CLI 时间 | ✅ V1.0.9 API layer, V1.0.10 Presentation layer, 顺序正确 |
| Q6 find_stages_needing | ✅ AND query (issubset) 正确, 未来 mode="any" 即可 |
| Q7 registered_at | ✅ 保留 (debug 价值高), 但建议改为非 Optional |
| Q8 Scope | ✅ 非常合理 (ADR-0030/0031/0032/0033 拆分优秀) |

---

## 5 项 Minor Revisions (合并前必改)

### 修订 1: 修正 "6 API" 描述

ChatGPT 指出 ADR §1.2 写 "6 个 Introspection API" 但实际列出 8 个 (info / describe_all / summary / list_builtin / list_third_party / find_stages_needing / to_dict / to_json)。

**修订**: 改为 "6 类 Introspection Capability (8 APIs)"

### 修订 2: 增加 source 校验说明

ChatGPT 建议 V1.x source 保持开放字符串但增加 VALID_SOURCES warning (不 raise, V1.1 严格)。

**修订**: ADR §3.3 增加 source 校验说明 + VALID_SOURCES 集合

### 修订 3: registered_at 改为非 Optional

ChatGPT 建议 `registered_at: datetime` (非 Optional)，因为 register() 永远生成 `datetime.now()`。

**修订**: ADR §2.1 StageInfo 改 `Optional[datetime]` → `datetime`

### 修订 4: 增加 serialization stability test

ChatGPT 建议增加 `test_to_json_schema_stable` — json.loads(registry.to_json()) 后检查 schema keys (stages / roles / capabilities / default_order)。

**修订**: ADR §6 测试策略增加 stability test

### 修订 5: 明确 find_stages_needing 语义

ChatGPT 要求明确：当前是 AND query (issubset), 未来可能加 mode="any"。

**修订**: ADR §2.1 find_stages_needing docstring 明确 AND 语义

---

## ChatGPT 推荐路线图

```
V1.0.9
  |-- ADR-0030 Registry Introspection
  |      + StageInfo / StageSummary
  |      + source / requires
  |      + dump API
  |
  |-- ADR-0031 Metadata Serialization
  |
  v
V1.0.10
  |-- Pipeline Introspection
  |      pipeline.describe() / pipeline.graph()
  |
  |-- CLI
  |      ai-hub stage list / info / dump
  |
  |-- Predicate API
  |
  v
V1.1
  |-- Plugin system
  |-- entry_points
  |-- registry versioning
  |-- runtime telemetry
```

> 这份 ADR 的成熟度已经接近 ADR-0028 / ADR-0026 水平，是 V1.0.x Runtime 演进中比较关键的一步。

---

## 原始审核回复

完整 ChatGPT 回复见 `docs/reviews/0030-adr-chatgpt-review-raw.txt`。
