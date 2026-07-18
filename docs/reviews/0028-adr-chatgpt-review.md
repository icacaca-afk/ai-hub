# V1.0.8 ADR-0028 Metadata Access API — ChatGPT Review

**ADR File:** `docs/adr/0028-metadata-access-api.md` (Draft, commit 98fc86f)
**Review Date:** 2026-07-18
**Reviewer:** ChatGPT (external)
**Raw Reply:** `0028-adr-chatgpt-review-raw.txt`
**Verdict:** ✅ **APPROVED 9.91/10** (0 Blocking Issues)

---

## 总评分

| 维度 | 分数 | 评价 |
|------|------|------|
| API Design | **10.0** | 5 getter + 1 resolver 职责清晰 |
| Runtime Consistency | **10.0** | RuntimeMetadata 成为 Facade, 不再是 Data Bag |
| Backward Compatibility | **10.0** | 零破坏, V1.0.7 全部 API 保留 |
| Encapsulation | **9.9** | resolver 抽取 4 级优先级 |
| Future Evolution | **9.8** | 未来 resolve_server_metrics / resolve_condition 复用 |
| Scope Control | **10.0** | 单一聚焦 ADR, 不错过 Stage Registry |
| **Overall** | **9.91** | **APPROVED** — V1.x 系列最"克制"的 ADR |

## 结论

> "这是目前 V1.x 系列里最"克制"的一次 ADR"
> "前几个版本都是增加新的 Runtime 能力（Pipeline、Retry、Condition、Hooks、RuntimeMetadata），而 ADR-0028 并没有增加新的能力，而是在收敛 API Surface"
> "这类 ADR 往往比增加功能更重要，因为它决定后续 API 是否稳定"

---

## 核心评价 (Q1-Q8)

### Q1 Getter Design — **10/10 (满分)**

> "目前：get_stop_reason() / get_metrics() / get_condition() / get_plan_progress() / get_custom() / resolve_stopped_by() — 职责划分非常清楚"
> "我不建议增加 get_all()。原因：一旦 get_all() 出现, 以后所有代码都会 runtime.get_all()["condition"], Facade 又退化成 dict"
> "保持：一个 Getter 对应一个 Runtime Concept"

**采纳：** 不加 get_all()，保持一对一

### Q2 Getter Return Copy — **满分 (刻意的不一致)**

> "metrics / plan 返回 copy, custom 返回引用。很多人觉得不一致"
> "我认为：这是刻意的不一致"
> "metrics：属于 Runtime, 外部不能修改"
> "plan：同理"
> "但是 custom：本来就是 Plugin Namespace, Plugin 就是要修改它"
> "否则：Plugin 改的是 copy, 完全没有意义"
> "因此：保持现状"

**采纳：** 保持当前 copy/reference 不一致设计（设计原则正确）

### Q3 resolve_stopped_by — **命名一致 Non-blocking**

> "我去年（上一轮）建议的那个方向。我仍然支持"
> "唯一建议：把 resolve_stopped_by(ctx) 改成 resolve_stop_reason(ctx)"
> "整个 Runtime API 已经统一 get_stop_reason(), 而不是 get_stopped_by()"
> "建议保持 Terminology 一致"
> "如果已经大量使用 stopped_by, 也没有必要为了命名一致性去 Breaking Change"
> "属于 Non-blocking"

**采纳 Non-blocking：** `resolve_stopped_by` → `resolve_stop_reason`（V1.0.8 实施时改名，与 `get_stop_reason` 命名一致）

### Q4 Checkpoint Refactor — **解耦**

> "我建议：不仅 resolve_stopped_by() 应该抽, 以后 Metrics 也应该抽"
> "例如：runtime.resolve_server_metrics(ctx) / runtime.resolve_condition(ctx) / runtime.resolve_retry(ctx)"
> "Checkpoint 完全变成：snapshot.stopped_by = runtime.resolve_stop_reason(ctx) / snapshot.metrics = runtime.resolve_metrics(ctx) / snapshot.condition = runtime.resolve_condition(ctx)"
> "Checkpoint 根本不知道 RuntimeMetadata 演进了多少版本"
> "这是很好的解耦。不过：不是 V1.0.8 必须"

**采纳：** V1.0.8 仅做 `resolve_stop_reason`（V1.0.9 评估 `resolve_server_metrics` 等）

### Q5 String vs Enum — **继续 String**

> "继续支持 String"
> "目前 Stop Reason 不断增加：condition:abort / condition:skip / retry:timeout / retry:exhausted / manual / cancel / hook / pipeline / planner..."
> "如果现在做 Enum, 以后 Enum 几乎每个版本都会改"
> "String Namespace 更灵活"
> "建议：直到 Stop Reason 真正稳定, 再做 Enum。至少 V2"

**采纳：** V1.0.8 保持 String，V2 评估 Enum

### Q6 Schema Version — **继续 Defer**

> "继续 Defer。目前没有 Serializer / Persistence Format / Remote RPC, Schema Version 就是 Dead Field"
> "以后 Stage Registry / Metadata Export / Snapshot Version 出来以后, 再引入"

**采纳：** V1.0.8 不加 schema_version

### Q7 ADR Scope — **强烈赞成小 ADR**

> "我非常赞成：不要 Mega ADR"
> "目前：0027 RuntimeMetadata → 0028 Metadata API → 0029 Stage Registry, 每一个只有一个主题"
> "Review 简单 / Git 容易回滚 / ADR 职责清晰"
> "千万不要：Metadata + Registry + Pipeline Introspection + Schema Version 全部塞一起, 后面没人 Review 得动"

**采纳：** V1.0.8 = ADR-0028 (Metadata API) + ADR-0029 (Registry) 独立

### Q8 V1.0.8 Priority — **采纳建议**

> "保持：0028 Metadata API → 0029 Registry"
> "Pipeline Introspection 放 V1.0.9"
> "因为 Registry 是 Introspection 的基础, 没有 Registry Introspection 只能继续遍历 Stage"

**采纳：** V1.0.8 = 0028 + 0029，V1.0.9 = Pipeline Introspection

---

## 🎁 One Recommendation (Non-blocking 采纳)

> "我建议：不要只提供 get_xxx(), 同时提供 has_xxx()"
> "例如：runtime.has_condition() / runtime.has_metrics() / runtime.has_stop_reason()"
> "比 if runtime.get_condition() is not None 可读性更好"
> "这是 API Human Factor。不是功能需求"

**采纳 Non-blocking：** V1.0.8 实施时加 5 个 `has_xxx()` 方法：
- `has_stop_reason() -> bool`
- `has_metrics() -> bool`
- `has_condition() -> bool`
- `has_plan_progress() -> bool`
- `has_custom(name: str) -> bool`

---

## V1.0.9 Roadmap (采纳 ChatGPT 9.91/10)

| 优先级 | 项目 | 说明 |
|--------|------|------|
| **MUST** | Stage Registry | StageDescriptor 注册 / 生命周期查询 / 能力索引 |
| **SHOULD** | Pipeline Introspection | pipeline.describe() / graph() / dump() / stage_names() / descriptors() |
| **SHOULD** | Metadata Access API 完整化 | has_xxx() / is_xxx() / runtime.is_stopped() / runtime.is_success() / runtime.stop_reason() |
| **LATER** | Metadata Export | runtime.to_dict() / to_json() / snapshot() |
| **LATER** | Schema Version | 等真正有跨版本持久化、导出或远程传输需求时再引入 |

---

## Adopt / Defer 总结

| 建议 | 结论 | 优先级 |
|------|------|--------|
| Metadata Access API | ✅ Adopt (已 DRAFT) | — |
| Resolver extraction | ✅ Adopt (已 DRAFT) | — |
| Getter defensive copy | ✅ Adopt (已 DRAFT) | — |
| String stop reason | ✅ Adopt (已 DRAFT) | — |
| Runtime Facade evolution | ✅ Adopt | — |
| `resolve_stopped_by` → `resolve_stop_reason` | 🟡 Adopt (Non-blocking) | 实施阶段改名 |
| `has_xxx()` 系列方法 | 🟡 Adopt (Non-blocking) | 实施阶段加 5 个方法 |
| `resolve_server_metrics` / `resolve_condition` | 🟡 V1.0.9 | Registry 后 |
| Bulk get_all() | ❌ Reject | — |
| Enum StopReason | 🟡 Defer (V2+) | — |
| Schema Version | 🟡 Defer | 真正需要时 |
| Pipeline Introspection | 🟡 V1.0.9 | — |
| Metadata Export | 🟡 Future | — |

---

## V1.0.8 实施下一步

1. ✅ V1.0.8 ADR-0028 Accepted (9.91/10)
2. 🔜 V1.0.8 实施：
   - 6 个方法 (5 getter + 1 resolver, 改名 resolve_stop_reason)
   - 5 个 `has_xxx()` 方法 (Non-blocking 采纳)
   - CheckpointStage 改用 resolver
   - 27+ 新增测试
3. 🔜 V1.0.8 代码层 ChatGPT 审核（期望 9.5+/10）
4. 🔜 V1.0.8 Final Accepted
5. 🔜 V1.0.8 ADR-0029 Stage Registry (ChatGPT 路线图 MUST)
