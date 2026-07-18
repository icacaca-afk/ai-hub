# V1.0.7 ADR-0027 Runtime Metadata Schema — ChatGPT Review (v2)

**ADR File:** `docs/adr/0027-runtime-metadata-schema.md` (Draft v2, commit dd66d8e)
**Review Date:** 2026-07-18
**Reviewer:** ChatGPT (external)
**Raw Reply:** `0027-adr-v2-chatgpt-review-raw.txt`
**Verdict:** ✅ **APPROVED 9.85/10** (Critical + 1 Non-blocking + 2 Runtime Contract MUSTs)

---

## 总评分

| 维度 | 分数 | v1 对比 | 评价 |
|------|------|---------|------|
| Architecture | **10.0** | 9.8 | 最高分（Additive 演进 + stopped_by 顶级） |
| Runtime Contract | **9.9** | 9.8 | + 2 MUST 强化（canonical source + write-through） |
| API Stability | **10.0** | 7.8 | +2.2 飞跃（additive 完整保留 metadata） |
| Backward Compatibility | **10.0** | 7.2 | +2.8 飞跃（第三方 Stage / Hook 100% 不受影响） |
| Extensibility | **9.9** | 10.0 | -0.1（轻微，custom namespace 仍 100% 保留） |
| Migration Strategy | **10.0** | — | 新维度，additive 满分 |
| Testability | **9.8** | 9.6 | +0.2（需补双写一致性 + 插件兼容测试） |
| **Overall** | **9.85** | 9.2 | **+0.65 飞跃**（从 NEEDS REVISION → APPROVED） |

## 结论

> "这是一个明显优于 v1 的方案。"
> "你实际上采用了我认为最关键的修正：把 RuntimeMetadata 从 '替换 metadata' 改成了 '新增 runtime'。"
> "这是目前 V1.x ADR 中最成熟的一份之一。"

---

## 最大改进

> "Keep ctx.metadata 100% intact, add ctx.runtime. 这一个决定基本解决了 v1 的阻塞问题。"

**v1 → v2 性质变化：**
- v1: API 重构 (Breaking Change) → 9.2/10
- v2: Runtime 能力增强 (Additive Change) → 9.85/10

```
metadata (dict) ──────────► Legacy API (V1.0.6 永久支持)
        │
        ▼
runtime (RuntimeMetadata) ─► New API (V1.0.7 强类型)
```

---

## Critical 采纳（架构级）

### ✅ C1. Additive Migration (CRITICAL)
- ✅ 100% 保留 `ctx.metadata: dict` (V1.0.6 行为完全不变)
- ✅ 新增 `ctx.runtime: RuntimeMetadata` (强类型)
- ✅ 第三方 Stage `ctx.metadata["key"] = value` 完全不受影响
- ✅ Hook 读 `ctx.metadata["key"]` 完全不受影响
- ✅ **零 Breaking Change**

### ✅ C2. Double Write Strategy (CRITICAL)
- ✅ built-in Stage **同时**写 `ctx.runtime.*` 和 `ctx.metadata["*"]`
- ✅ 这是 Compatibility Bridge, 让两个世界互不影响
- ✅ 迁移真正困难的是读，不是写 — Double Write 解决读端兼容

### ✅ C3. `stopped_by` 顶级字段 (CRITICAL)
- ✅ 从 `condition_eval.stopped_by` (V1.0.4 嵌套) → `ctx.runtime.stopped_by` (顶级)
- ✅ 未来 Retry / Timeout / ManualAbort / Cancellation / Hook / Policy 统一写 `runtime.stopped_by`
- ✅ Architecture Improvement

### ✅ C4. 保留 `ctx.metadata` (CRITICAL)
- ✅ V1.x metadata **永远 Supported**（明确写入 ADR）
- ✅ **不**加 Warning（避免污染用户日志）
- ✅ 真正 Deprecation 在 V2

### ✅ C5. RuntimeMetadata dataclass (CRITICAL)
- ✅ 简单、强类型、运行时一致
- ✅ 不引入 Pydantic 依赖

### ✅ C6. **新增：Runtime Contract MUST** (CRITICAL)
> "RuntimeMetadata MUST be the canonical source for all built-in runtime state."

- ✅ built-in Stage **只**读 `ctx.runtime.*`
- ✅ `ctx.metadata["*"]` 仅作向后兼容读取
- ✅ 避免双向同步导致的 Bug

### ✅ C7. **新增：Runtime Contract MUST** (CRITICAL)
> "metadata compatibility is write-through only."

- ✅ 双写方向明确：`runtime → metadata`（写穿）
- ✅ **不**做 `metadata → runtime` 反向同步
- ✅ 避免双向同步 Bug

---

## Non-blocking 采纳

### 🔄 N1. Double Write 封装到 Runtime API
> "建议：不要让所有 Stage 自己 Double Write。建议抽出来。例如：ctx.runtime.set_condition_eval(...)，内部自动同步 metadata。这样以后 V2 删除 metadata 只需要改一个地方。"

- ✅ 实施时在 `RuntimeMetadata` 内部封装 `set_condition_eval()` / `set_server_metrics()` / `set_plan()` 等 helper
- ✅ Stage 调用 helper，**不**直接散落双写
- ✅ V2 删除 metadata 兼容性时，只需修改 RuntimeMetadata 内部

---

## Defer（采纳 ChatGPT 建议）

| 字段 | 决策 | 原因 |
|------|------|------|
| `retry` | V1.1 | RetryStage 真正 metadata 还没稳定 |
| `experimental` | V2 | 现在没有真实消费者，Runtime Contract 不用解释 Reserved Field |
| `schema_version` | V1.0.8 | V1.0.7 不要加（"几年：没人用"），V1.0.8 如果 Registry 真正需要再加 |

---

## 新增测试要求

### ✅ T1. 双写一致性 (write-through only)
- ✅ `ctx.runtime.condition_eval = X` → `ctx.metadata["condition_eval"]` 一致
- ✅ 反向：写 `ctx.metadata["abc"] = 1` **不会**自动同步到 `ctx.runtime`
- ✅ 明确：单向同步

### ✅ T2. Plugin Compatibility (V1.0.6 旧风格)
- ✅ 模拟 V1.0.6 第三方 Plugin：`ctx.metadata["abc"] = 1`
- ✅ Pipeline 正常
- ✅ Checkpoint 正常
- ✅ Runtime 不受影响

---

## 评分维度（详细）

### Q1 Additive Migration — ✅ 已解决
> "我认为已经解决。甚至我建议 Runtime Contract 可以明确写一句：RuntimeMetadata is additive and MUST NOT invalidate any existing metadata usage during V1.x. 这样未来任何人都不能 ctx.metadata = RuntimeMetadata(...)，避免 ADR 自己以后被推翻。"

**采纳** → 新增 §10 Runtime Contract MUST（写入 ADR §10.1）

### Q2 字段集合 — ✅ 合理
> "V1.0.7: server_metrics / condition_eval / stopped_by / plan / custom 即可。十分干净。"

**采纳** → 字段集保持精简，retry/experimental 已 defer

### Q3 Double Write — ✅ 采纳
> "必须 Double Write。... 我唯一建议：抽出来。ctx.runtime.set_condition_eval(...)，内部自动同步 metadata。"

**采纳 Non-blocking N1** → 实施时封装 helper

### Q4 stopped_by — ✅ 采纳
> "这是整个 ADR 最漂亮的决定。"

**采纳** → 顶级字段实施

### Q5 不 Deprecate metadata — ✅ 采纳
> "V1.x 不用 Warning。原因：Warning 反而污染用户日志。真正 Deprecated 应该 V2。"

**采纳** → ADR §10.2 明确"metadata 永远 Supported"

### Q6 schema_version — ✅ Defer
> "这是唯一一个我建议现在不要加。很多项目喜欢 schema_version=1，实际上几年没人用。真正 Schema Migration 开始需要 Version 时再加。否则它就是 Dead Field。建议 V1.0.8 如果 Registry 真正需要再加入。"

**采纳** → V1.0.7 不加，V1.0.8 评估

### Q7 Tests — ✅ 采纳 + 2 个新增
> "26 个测试已经不错。不过我建议补两个：① 双写一致性 ② Plugin Compatibility"

**采纳 T1 + T2** → 28 个测试

### Q8 V1.0.8 优先级
> "MUST: Stage Registry. SHOULD: Metadata Access API. LATER: Schema Versioning."

**采纳** → V1.0.8 路线图

---

## V1.0.7 → V1.0.8 演进（采纳 ChatGPT 建议）

| 优先级 | 项目 | 说明 |
|--------|------|------|
| **MUST** | Stage Registry | 统一注册 / 发现 / 查询 Stage，StageDescriptor + RuntimeMetadata 两条主轴已稳定 |
| **SHOULD** | Metadata Access API | 统一访问 RuntimeMetadata 接口（如 `ctx.runtime.get(...)`） |
| **LATER** | Schema Versioning | 仅当 RuntimeMetadata 跨版本迁移需求时再引入 |

**Runtime Contract 新增 MUST：**
- `RuntimeMetadata MUST be the canonical source for all built-in runtime state.`
- `metadata compatibility is write-through only.`

---

## Adopt / Defer 总结

| 建议 | 结论 | 优先级 |
|------|------|--------|
| Additive Migration | **Adopt** | Critical |
| Double Write | **Adopt** | Critical |
| stopped_by 一级字段 | **Adopt** | Critical |
| 保留 metadata | **Adopt** | Critical |
| RuntimeMetadata dataclass | **Adopt** | Critical |
| runtime 成为 Built-in Canonical Source | **Adopt** | Critical |
| metadata write-through only | **Adopt** | Critical |
| Double Write 封装到 Runtime API | **Adopt** | Non-blocking |
| schema_version | **Defer** | V1.0.8 |
| retry | **Defer** | V1.1 |
| experimental | **Defer** | V2 |

---

## V1.0.7 实施下一步

1. ✅ V1.0.7 ADR v2 Accepted
2. 🔜 V1.0.7 实施：
   - `planner/runtime_metadata.py` (NEW, 含 `set_condition_eval()` 等 helper)
   - `planner/pipeline.py` 新增 `runtime: RuntimeMetadata` 字段
   - 5 个 built-in Stage 通过 helper 双写
   - `tests/test_runtime_metadata.py` (12+ tests)
   - `tests/test_plugin_compatibility.py` (T1 + T2 新增)
3. 🔜 V1.0.7 代码层 ChatGPT 审核（期望 9.5+/10）
4. 🔜 V1.0.8 Stage Registry (MUST)
