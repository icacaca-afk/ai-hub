# V1.0.10 ADR-0031 Metadata Serialization — ChatGPT ADR Review (Summary)

- **审核类型**: ADR 审核 (pre-implementation)
- **ADR**: docs/adr/0031-metadata-serialization.md
- **审核时间**: 2026-07-19
- **总分**: **9.6 / 10** ✅ APPROVED
- **Blocking**: 2 项 (Blocking-1 hallucination, Blocking-2 已采纳)
- **Raw**: `0031-adr-chatgpt-review-raw.txt`

## 八维评分

| # | 维度 | 分数 | 评价 |
|---|------|------|------|
| 1 | 架构方向 | 9.8/10 | 独立 serialization layer 是正确方向，SRP 边界清晰 |
| 2 | API 一致性 | 9.5/10 | to_dict() + serialize_xxx() 双 API 略增加表面积，但合理 |
| 3 | 向后兼容 | 9.8/10 | delegate + deprecated alias 策略优秀 |
| 4 | 数据结构/schema | 9.6/10 | R4 stability 思路正确，暂不引 schema_version 明智 |
| 5 | Reject Alternatives | 9.5/10 | 大部分拒绝理由充分 |
| 6 | 测试策略 | 9.4/10 | 覆盖全面，建议增加 property testing |
| 7 | 实施计划 | 9.7/10 | 五阶段拆解合理，风险低 |
| 8 | V1.1 演化规划 | 9.6/10 | deferred 策略正确，没有提前设计 |

**平均: ⭐ 9.6 / 10**

## 总评

ADR-0031 是 V1.0.6～V1.0.9 metadata 体系自然演进的一步。核心判断正确：

> Metadata 已经从单一对象演化为 Registry / Runtime / Descriptor 多维状态，继续让每个模块自行序列化会产生 schema 漂移，因此需要一个独立 serialization boundary。

**最大优点**:
- 没有过早引入 schema version
- 没有扩大 Core Freeze 破坏面
- 保留 backward compatibility
- serialization responsibility 从 Registry 中剥离
- 为 V1.0.11 Pipeline Introspection 和 CLI Introspection 提供基础设施

> V1.0.6～V1.0.9 是"建立 metadata"。V1.0.10 开始是：把 metadata 变成可被系统外部消费的稳定协议层。这是从内部框架走向平台化的一个关键节点。

## Q1-Q8 逐项结论

### Q1: 序列化模块位置 ✅ (9.8/10)

**结论**: 当前 `planner/metadata_serialization.py` 最佳。

```
planner/
├── stage_descriptor.py
├── runtime_metadata.py
├── stage_registry.py
└── metadata_serialization.py   ← V1.0.10 NEW
```

符合 V1.0.x 扁平结构。V1.1/V2 出现 `MetadataSchema` / `MetadataMigration` / `MetadataVersion` / `MetadataValidator` 时再升级为 `planner.metadata/` 子包。

### Q2: 双 API 是否过设计？ ✅ (9.5/10)

**结论**: 保留。两个用户群：
- 使用者: `descriptor.to_dict()` (Pythonic, CLI 友好)
- 框架内部: `[serialize_descriptor(d) for d in descriptors]` (functional, 易组合)

**约束补充**: `serialize_xxx()` 是 canonical implementation，`to_dict()` 永远只是 facade，避免 `to_dict()` 出现业务逻辑。

### Q3: StageDescriptor.to_dict() 破坏 Core Freeze？ ✅ (9.9/10)

**结论**: 不破坏。

V1.0.6 freeze 的核心应该理解为：
- **冻结**: 字段 / 构造方式 / 语义
- **不是冻结**: 方法扩展

`@dataclass(frozen=True) class StageDescriptor: def to_dict()` 不改变 `hash()` / `eq()` / `immutability()`，属于 **additive API extension**，不是 breaking change。

### Q4: lazy import 是否合理？ ✅ (9.7/10)

**结论**: 当前方案最佳。

避免 `stage_descriptor → metadata_serialization → stage_descriptor` 循环。不建议 Protocol — Protocol 解决 interface dependency，不是 module cycle。lazy import 更简单。

### Q5: ConditionEval.to_dict() 保留还是移除？ ✅ (9.8/10)

**结论**: (a) 保留 method。

V1.0.4 `ConditionEval.to_dict()` 已存在，删除属于 unnecessary breaking change。不建议 DeprecationWarning（不是错误 API，只是实现迁移）。

**迁移路径**: V1.0.10 delegate → V1.1 继续保留 → V2 再考虑删除。

### Q6: RuntimeMetadata 合并 ctx.metadata？ ✅ (9.9/10)

**结论**: (a) 仅包含 RuntimeMetadata 字段。

**重要边界**:
- `RuntimeMetadata`: 回答 "execution runtime state"
- `ctx.metadata`: 回答 "arbitrary user context"

混合会导致 `RuntimeMetadata.to_dict()` 变成 "dump everything"，违反 SRP。未来如需合并，应增加 `ctx.to_dict()` 或 `serialize_execution_context(ctx)`，不要污染 RuntimeMetadata。

### Q7: serialize_xxx 加 schema_version 参数？ ✅ (9.7/10)

**结论**: ❌ 不加入。

V1.0.x 只有一个 schema，提前加 `schema_version=1` 会制造未来负担。V1.1 演进方案: `serialize_descriptor(d, schema=MetadataSchema.V1)` 而非裸 int。

### Q8: 测试覆盖是否足够？ ✅ (9.4/10)

**结论**: 基本足够（30 tests 合理）。

**建议增加**:
1. **round-trip stability**:
   ```python
   def test_json_round_trip():
       data = serialize_descriptor(d)
       text = to_json(data)
       assert json.loads(text) == data
   ```
2. **no mutation property** (扩展 immutable_input):
   ```python
   before = copy.deepcopy(rm)
   serialize_runtime_metadata(rm)
   assert rm == before
   ```

## Blocking Issues

### Blocking-1: ADR 代码示例 typo / 截断错误 ❌ (Hallucination)

ChatGPT 提到 `has_side_effeways_run_after_stop` / `serialize_desccriptor` / `return {"stage":,}` 等 typo。

**验证结果**: ADR 中**无**这些 typo (`Grep` 全文搜索确认)。ChatGPT hallucination。

**处理**: 标记为 hallucination，无需修改 ADR。在 review summary 记录此情况。

### Blocking-2: 明确 canonical API ✅ (已采纳)

ChatGPT 建议 §3.2 增加:
> `serialize_xxx()` is canonical serialization implementation. `to_dict()` methods are convenience wrappers only.

**采纳**: 已在 ADR §3.2 补充此约束。

## Non-blocking Suggestions

### 建议 1 (V1.1 deferred): TypedDict for schema typing

```python
class StageDescriptorDict(TypedDict):
    name: str
    role: str
    ...
```

**Defer to V1.1** — V1.0.10 保持 `Dict[str, Any]` 简单。

### 建议 2 (已采纳): 重命名 METADATA_SCHEMA_VERSION

当前 `METADATA_SCHEMA_VERSION: Optional[int] = None` 略像已启用。

**采纳**: 改为 `FUTURE_METADATA_SCHEMA_VERSION: Optional[int] = None` (V1.1 启用)，减少误解。

### 建议 3 (已确认): StageRegistry.to_dict() 用 serialize_stage_info

```python
# 当前 ADR 设计 (正确):
"stages": [serialize_stage_info(info) for info in self._info.values()],
```

**保持** — 更符合 canonical 原则（不用 `info.to_dict()` facade）。

## V1.0.10 合并建议 (commit 顺序)

ChatGPT 推荐 5 个独立 commits:
1. `add planner/metadata_serialization.py`
2. `add to_dict() facade methods`
3. `migrate ConditionEval`
4. `migrate StageRegistry helper`
5. `tests + regression`

**采纳**: 实施时按此顺序提交（清晰可回溯）。

## V1.0.11 ADR-0032 路线建议

| 优先级 | ADR | 内容 |
|--------|-----|------|
| **P0** | ADR-0032 Pipeline Introspection | `pipeline.describe()` / `pipeline.graph()` → `{"stages": [...], "edges": [...]}` |
| P1 | ADR-0033 Predicate API | `registry.find(role=, capability=, requires=, source=)` 统一查询 |
| P2 | ADR-0034 CLI Introspection | `ai-hub stage list / info / dump` (依赖 0031 + 0032) |

## Final Approval

```
V1.0.10 ADR-0031 Metadata Serialization

状态:       ✅ APPROVED
评分:       9.6 / 10
Blocking:   2 项 (Blocking-1 hallucination 不存在, Blocking-2 已采纳)
Non-blocking: 3 项 (建议1 V1.1 deferred, 建议2 已采纳, 建议3 已确认)

Decision:   ✅ MERGE (修复 Blocking-2 后)

Next:       V1.0.10 implementation (5 commits)
            → V1.0.11 ADR-0032 Pipeline Introspection
```

## Adopted Revisions Summary

- **R1** (Blocking-2 采纳): §3.2 明确 `serialize_xxx()` 是 canonical, `to_dict()` 是 facade
- **R2** (建议2 采纳): `METADATA_SCHEMA_VERSION` → `FUTURE_METADATA_SCHEMA_VERSION`
- **R3** (建议3 确认): `StageRegistry.to_dict()` 用 `serialize_stage_info()` (canonical)
- **R4** (Q8 采纳): §6 测试策略增加 `test_json_round_trip` + `test_no_mutation_property`
- **R5** (commit 顺序采纳): §7 实施计划明确 5 个独立 commits
