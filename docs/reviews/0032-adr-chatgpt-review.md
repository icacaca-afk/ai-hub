# ADR-0032 ChatGPT Review — Conditional Approve 9.4/10

## 总评

**评分**: 9.4/10
**结论**: Conditional Approve

整体架构无需重做；职责边界、Registry 解耦、Descriptor 模式、R1 facade 和"只描述不执行"都已经正确。

## 3 个 P0 修正项

### P0-1: edge endpoint 改用稳定结构 ID
- 不使用 stage name 作为 edge identity
- 改用 `pre:0`, `post:0`, `bridge` 等结构 ID
- 防止 duplicate stage names 产生歧义

### P0-2: Bridge 成为序列化结构中可解析的 virtual node
- Bridge 需要在 stages 列表中正式存在
- 保证 graph closure (edge endpoint 必须能在 node 集合中找到)
- Bridge 作为 synthetic node: `{id: "bridge", name: "__bridge__", role: "bridge", position: "bridge"}`

### P0-3: PipelineDescriptor.version 语义明确
- V1.0.11 应为 `version = "1.0.11"` (不是 1.0.10)
- 明确它是 producer/API version，不是 schema_version
- 不偷偷变成 schema_version (与 ADR-0031 deferred 一致)

## 额外建议 (非阻塞)

1. **serialize_pipeline() MUST consume PipelineDescriptor**, not ExecutionPipeline
2. **R1 硬约束**: 写入 ADR 作为 architecture invariant
3. **单向转换链**: ExecutionPipeline → PipelineDescriptor → dict → JSON
4. **role 推断基于类型而非 name**: `_STAGE_ROLE_MAP` 用 `type(stage).__name__` 而非 `stage.name`
5. **has_hooks 语义**: 表示"实际配置了至少一个 Hook"，而非"存在 Hook 容器"
6. **空结构定义**: 四种空 Pipeline 都要有明确 schema (pre+post / only pre / only post / neither)
7. **测试补充**: duplicate_stage_names / empty_pipeline / pre_only / post_only / descriptor_is_snapshot / custom_stage_name_does_not_change_role / bridge_endpoint_resolves / to_json_facade_delegation
8. **"existing_tests_pass" 改为 execution contract regression test**

## 最终 schema 建议

```json
{
  "name": "default",
  "stages": [
    {"id": "pre:0", "name": "route", "role": "router", "position": "pre", "index": 0},
    {"id": "bridge", "name": "__bridge__", "role": "bridge", "position": "bridge", "index": 1},
    {"id": "post:0", "name": "metrics", "role": "metrics", "position": "post", "index": 0}
  ],
  "edges": [
    {"from": "pre:0", "to": "bridge", "type": "pre_to_bridge"},
    {"from": "bridge", "to": "post:0", "type": "bridge_to_post"}
  ],
  "has_router": true,
  "has_quota": false,
  "has_hooks": false
}
```

## 架构链

```
Stage identity → Runtime metadata → Registry → Registry introspection → Metadata serialization → Pipeline introspection → CLI / Web UI / MCP / observability
```

## Open Questions 结论

| Question | 结论 |
|----------|------|
| name="default" 自定义 | V1.0.11 不开放，保持 default |
| __bridge__ 命名 | 合适作为展示名；edge 用 stable id "bridge" |
| _STAGE_ROLE_MAP 位置 | 暂留 stage_descriptor.py |
| linear vs DAG | 坚定 linear |

## Rejected Alternatives 审核

四个全部批准 (R-A, R-B, R-C, R-D)
