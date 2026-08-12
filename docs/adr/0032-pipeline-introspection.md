# ADR-0032: Pipeline Introspection

| Field | Value |
|-------|-------|
| Status | Proposed |
| Date | 2026-08-13 |
| Decider | User + ChatGPT (ADR Review) |
| Supersedes | — |
| Superseded by | — |
| Related | ADR-0029 (Stage Registry), ADR-0030 (Registry Introspection), ADR-0031 (Metadata Serialization) |

## 1. Context

### 1.1 背景

V1.0.6–V1.0.10 完成了 Stage 元数据的可观察性建设：

| Version | Capability |
|---------|-----------|
| V1.0.6 | StageDescriptor — Stage 身份定义 |
| V1.0.7 | RuntimeMetadata — Stage 运行时状态 |
| V1.0.8 | StageRegistry — Stage 注册与发现 |
| V1.0.9 | Registry Introspection — Registry.describe() / summary() / to_dict() |
| V1.0.10 | Metadata Serialization — 统一序列化层 (canonical API + facade) |

ChatGPT V1.0.10 审核建议：

> 下一步自然：整个 Pipeline 描述。
> `pipeline.describe()` 输出 stages + edges。
> 这会成为 CLI 基础 / Web UI 基础 / MCP 基础。

### 1.2 问题

`ExecutionPipeline` 当前没有 introspection 能力：

- 无法查询 Pipeline 由哪些 Stage 组成
- 无法查询 Stage 之间的执行顺序 / 依赖关系
- 无法将 Pipeline 结构序列化为 JSON（供 CLI / Web UI / MCP 消费）
- `pre_bridge_stages` 和 `post_bridge_stages` 是 plain list，没有元数据

### 1.3 目标

- `pipeline.describe()` 返回 Pipeline 结构化描述（stages + edges + metadata）
- `pipeline.to_dict()` 返回可 JSON 序列化的 dict
- `pipeline.to_json()` 返回 JSON 字符串
- 复用 V1.0.10 `metadata_serialization.py` canonical API
- 不修改 `ExecutionPipeline.run()` 执行路径

### 1.4 非目标

- ❌ 不做 Pipeline 可视化（DOT / Mermaid graph）
- ❌ 不做 Pipeline 编辑（动态增删 Stage）
- ❌ 不做 Pipeline 执行 trace（运行时事件流 → V1.0.13+）
- ❌ 不做 Predicate API（V1.0.12 ADR-0033）
- ❌ 不做 CLI Introspection（V1.0.13 ADR-0034，依赖本 ADR）
- ❌ 不修改 `ExecutionPipeline.run()` 执行逻辑

## 2. Decision

### 2.1 PipelineDescriptor dataclass

新增 `planner/pipeline_descriptor.py`：

```python
@dataclass(frozen=True)
class PipelineDescriptor:
    """Pipeline 结构描述（不可变值对象）。"""
    name: str                          # Pipeline 名称（默认 "default"）
    pre_bridge: Tuple[StageDescriptor, ...]   # pre-bridge stages
    post_bridge: Tuple[StageDescriptor, ...]  # post-bridge stages
    has_router: bool                   # 是否配置了 Router
    has_quota: bool                    # 是否配置了 QuotaManager
    has_hooks: bool                    # 是否配置了 Hooks
    version: str = "1.0.10"            # 创建时的 ai-hub 版本
```

设计约束：
- `frozen=True` — 不可变值对象（与 StageDescriptor 一致）
- `Tuple` 而非 `List` — 不可变 + hashable
- StageDescriptor 复用 V1.0.6 定义，不新建
- `version` 记录创建时版本，V1.1 改为 `schema_version`

### 2.2 Pipeline Edge 模型

执行顺序通过 edges 隐式表达：

```
pre_bridge:  [RouteStage] → Bridge (implicit) → post_bridge: [Retry, Metrics, Condition, Checkpoint]
```

`to_dict()` 输出 edges 为显式列表：

```json
{
  "name": "default",
  "stages": [
    {"name": "route", "role": "router", "position": "pre_bridge", "index": 0},
    {"name": "retry", "role": "retry", "position": "post_bridge", "index": 0},
    {"name": "metrics", "role": "metrics", "position": "post_bridge", "index": 1}
  ],
  "edges": [
    {"from": "route", "to": "__bridge__", "type": "pre_to_bridge"},
    {"from": "__bridge__", "to": "retry", "type": "bridge_to_post"},
    {"from": "retry", "to": "metrics", "type": "sequential"}
  ],
  "has_router": true,
  "has_quota": false,
  "has_hooks": true
}
```

Edge 类型：
- `pre_to_bridge` — pre-bridge 最后一个 Stage → Bridge
- `bridge_to_post` — Bridge → post-bridge 第一个 Stage
- `sequential` — 同列表内前一个 Stage → 后一个 Stage

### 2.3 ExecutionPipeline 新增方法

在 `planner/pipeline.py` 的 `ExecutionPipeline` 类上新增：

```python
def describe(self) -> PipelineDescriptor:
    """返回 Pipeline 结构描述。"""

def to_dict(self) -> Dict[str, Any]:
    """返回可 JSON 序列化的 dict（facade, delegate to serialize_pipeline）。"""

def to_json(self, *, indent: Optional[int] = 2) -> str:
    """返回 JSON 字符串。"""
```

约束：
- `describe()` 返回 `PipelineDescriptor`（值对象）
- `to_dict()` 是 facade，delegate 到 `serialize_pipeline()` (R1 约束，与 V1.0.10 一致)
- `to_json()` delegate 到 `metadata_serialization.to_json()`
- 不修改 `run()` / `_base_execute()` / `assemble_result()` 等现有方法

### 2.4 serialize_pipeline() canonical function

在 `planner/metadata_serialization.py` 新增：

```python
def serialize_pipeline(pd: PipelineDescriptor) -> Dict[str, Any]:
    """序列化 PipelineDescriptor 为 dict。"""
```

输出 schema：

```python
{
    "name": str,
    "stages": List[Dict],      # 每个 stage: {name, role, position, index}
    "edges": List[Dict],       # 每个 edge: {from, to, type}
    "has_router": bool,
    "has_quota": bool,
    "has_hooks": bool,
}
```

注意：
- 不输出 `version` 字段（V1.0.10 不引入 schema_version，与 ADR-0031 一致）
- `stages` 按执行顺序排列（pre_bridge 先，post_bridge 后）
- `edges` 用 `__bridge__` 作为虚拟节点表示 Bridge 位置

### 2.5 Stage name 提取策略

ExecutionPipeline 的 `pre_bridge_stages` / `post_bridge_stages` 是 `list`，元素是 `ExecutionStage` Protocol 实例。

Stage name 提取规则：
1. 如果 stage 有 `.name` 属性（property）→ 用 `stage.name`
2. 如果 stage 是 RouteStage → `"route"`
3. fallback → `stage.__class__.__name__.lower()`

### 2.6 Stage role 提取策略

从 StageRegistry 查询（如果 stage 已注册）：
1. 用 stage name 查 `StageRegistry.describe(name)` 获取 `StageDescriptor.role`
2. 如果未注册 → 用类名推断：`RouteStage` → `"router"`，`MetricsStage` → `"metrics"` 等
3. fallback → `"unknown"`

约束：`pipeline.describe()` **不依赖** StageRegistry（Pipeline 可以在没有 Registry 的情况下工作）。如果需要 role 信息，通过 `StageDescriptor.from_stage()` 工具方法提取（见 §2.7）。

### 2.7 StageDescriptor.from_stage() classmethod

在 `planner/stage_descriptor.py` 新增：

```python
@classmethod
def from_stage(cls, stage: ExecutionStage, position: str = "", index: int = -1) -> "StageDescriptor":
    """从 Stage 实例推断描述信息。"""
```

推断规则：
- `name` → `stage.name` 或 `stage.__class__.__name__.lower()`
- `role` → 预设映射表（route→router, metrics→metrics, retry→retry, condition→condition, checkpoint→checkpoint）
- `requires` → `frozenset()`（无信息时不猜）
- `provides` → `frozenset()`
- `description` → `""`（不猜）

映射表定义在 `stage_descriptor.py` 内部（`_STAGE_ROLE_MAP`），不导入 `pipeline.py`（避免循环依赖）。

## 3. Consequences

### 3.1 正面

- Pipeline 结构可观察 → CLI / Web UI / MCP 可消费
- 复用 V1.0.10 序列化层，保持架构一致性
- 不修改执行路径，零运行时风险
- PipelineDescriptor 是不可变值对象，安全传递

### 3.2 负面

- `from_stage()` 推断的 role 可能不准确（未注册的 Stage）
- edges 模型简单（线性 + 一个 bridge 节点），不支持未来 DAG Pipeline
- 新增 `pipeline_descriptor.py` 文件增加模块数量

### 3.3 缓解

- role 推断标注 `"unknown"` 而非猜测，用户可手动注册到 StageRegistry 获取准确信息
- edges 模型在 V1.0.x 足够（Pipeline 是线性执行），DAG 支持是 V2.0 话题
- 模块数 +1 可接受（与 StageDescriptor / RuntimeMetadata 一致的粒度）

## 4. Frozen Boundary Check

| Module | Modification | Status |
|--------|-------------|--------|
| `core/` | 0 修改 | ✅ Core Freeze (ADR-0008) |
| `router/router.py` | 0 修改 | ✅ |
| `router/health_router.py` | 0 修改 | ✅ |
| `router/score_router.py` | 0 修改 | ✅ |
| `providers/` | 0 修改 | ✅ |
| `planner/pipeline.py` | 新增 3 个方法 (`describe` / `to_dict` / `to_json`) | ⚠️ 非冻结 |
| `planner/stage_descriptor.py` | 新增 `from_stage()` classmethod + `_STAGE_ROLE_MAP` | ⚠️ 非冻结 |
| `planner/metadata_serialization.py` | 新增 `serialize_pipeline()` | ⚠️ 非冻结 |

说明：`planner/` 不在 Core Freeze 范围内（ADR-0008 只冻结 `core/` + `router/router.py`）。planner/ 的修改遵循 V1.0.10 的 facade + canonical 模式。

## 5. Test Plan

### 5.1 新增测试文件

`tests/test_pipeline_introspection.py`

### 5.2 测试矩阵

| Test Class | Count | 覆盖 |
|-----------|-------|------|
| TestPipelineDescriptor | 5 | dataclass 不可变 / 字段完整性 / Tuple 类型 / version 默认值 / hashable |
| TestSerializePipeline | 6 | returns_dict / stages_order / edges_correct / bridge_node / has_flags / schema_stable |
| TestPipelineDescribe | 5 | returns_descriptor / pre_bridge_stages / post_bridge_stages / has_flags / stage_count |
| TestPipelineToDict | 4 | facade_delegates_to_serialize / idempotent / stages_have_position_index / no_execution_side_effect |
| TestPipelineToJson | 3 | default_indent / compact / ensure_ascii_false |
| TestFromStage | 4 | known_stage_route / known_stage_metrics / unknown_stage / name_fallback |
| TestEdgeModel | 3 | pre_to_bridge / bridge_to_post / sequential |
| TestSchemaStability | 2 | no_schema_version / keys_stable |
| TestBackwardCompat | 2 | run_unchanged / existing_tests_pass |

**总计：34 tests**

### 5.3 关键测试断言

1. `pipeline.describe()` 不触发 `pipeline.run()`（无副作用）
2. `to_dict()` 输出 stages 按 pre_bridge → post_bridge 顺序
3. edges 包含 `__bridge__` 虚拟节点
4. `from_stage(RouteStage())` 返回 `name="route"`, `role="router"`
5. 现有测试零回归（331+ tests 全通过）

## 6. Implementation Plan

### 阶段 1：PipelineDescriptor + from_stage()
1. 创建 `planner/pipeline_descriptor.py`（PipelineDescriptor dataclass）
2. 在 `planner/stage_descriptor.py` 新增 `from_stage()` + `_STAGE_ROLE_MAP`

### 阶段 2：serialize_pipeline()
3. 在 `planner/metadata_serialization.py` 新增 `serialize_pipeline()` + 更新 `__all__`

### 阶段 3：ExecutionPipeline 方法
4. 在 `planner/pipeline.py` 的 `ExecutionPipeline` 新增 `describe()` / `to_dict()` / `to_json()`

### 阶段 4：测试
5. 创建 `tests/test_pipeline_introspection.py`（34 tests）
6. 运行全量回归测试

### 阶段 5：ADR + commit
7. commit ADR-0032
8. 发 ChatGPT ADR 审核

## 7. Open Questions

1. `PipelineDescriptor.name` 是否需要自定义？默认 `"default"` 是否足够？
2. edges 中 `__bridge__` 命名是否合适？替代方案：`"bridge"` / `"_bridge_"` / `"__base_execute__"`
3. `from_stage()` 的 role 映射表是否应该放在 `stage_descriptor.py` 还是单独配置文件？

## 8. Future Considerations

- **V1.0.12**：ADR-0033 Predicate API — `registry.find(role=, capability=)`
- **V1.0.13**：ADR-0034 CLI Introspection — `ai-hub pipeline describe --json`
- **V1.1**：引入 `schema_version`（与 ADR-0031 一致 deferred）
- **V2.0**：DAG Pipeline（如果需要非线性执行图）
- **V1.0.13+**：Pipeline 执行 trace（运行时事件流，非静态结构）

## 9. Rejected Alternatives

### R-A: 直接在 ExecutionPipeline 上加 to_dict()（不建 PipelineDescriptor）

拒绝原因：与 StageDescriptor / RuntimeMetadata 的值对象模式不一致。describe() 返回 dataclass 允许类型安全和 IDE 自动补全。

### R-B: edges 用 DAG 通用模型（支持未来非线性 Pipeline）

拒绝原因：V1.0.x Pipeline 是线性执行（pre → bridge → post），DAG 模型过度设计。V2.0 如果需要 DAG，新增 ADR。

### R-C: 从 StageRegistry 获取 Stage 元数据

拒绝原因：Pipeline 不应依赖 Registry。Pipeline 和 Registry 是独立组件：Pipeline 描述执行结构，Registry 管理 Stage 注册。耦合会导致 Pipeline 无法独立使用。

### R-D: pipeline.describe() 输出 Mermaid/DOT graph

拒绝原因：可视化是 CLI/Web UI 的职责，不是 Pipeline introspection 的职责。to_dict() 输出结构化数据，消费者自行渲染。
