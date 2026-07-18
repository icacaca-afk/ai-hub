# ADR-0028: Metadata Access API (V1.0.8)

- **里程碑**: V1.0.8
- **作者**: ai-hub core team
- **日期**: 2026-07-18
- **状态**: **Draft** (待 ChatGPT 审核)
- **依赖**: [ADR-0027 RuntimeMetadata](0027-runtime-metadata-schema.md) (V1.0.7 Accepted 9.88/10)
- **后续**: V1.0.8 ADR-0029 Stage Registry / Pipeline Introspection
- **ChatGPT 路线图**: V1.0.7 代码审核 9.88/10 Q8 — "V1.0.8: Metadata Access API (MUST)"

> **StageDescriptor 答 "What is a Stage?" (静态)**
> **RuntimeMetadata 答 "What happened during execution?" (动态)**
> **Metadata Access API 答 "How to access this data uniformly?" (接口)**
> **本 ADR 在 V1.0.7 RuntimeMetadata 基础上加统一访问接口, 替代散落的 `ctx.runtime.xxx` 直读。**

---

## 1. 背景与目标

### 1.1 背景

V1.0.7 RuntimeMetadata 引入了强类型运行时元数据容器 (5 个字段: server_metrics / condition_eval / stopped_by / plan / custom)。但访问方式仍散落：

```python
# V1.0.7 现状 (散落访问)
stopped_by = ctx.runtime.stopped_by
metrics = ctx.runtime.server_metrics
condition = ctx.runtime.condition_eval
plan = ctx.runtime.plan
my_plugin_data = ctx.runtime.custom.get("my_plugin", None)
```

**问题：**
1. **CheckpointStage 优先级逻辑重复**：V1.0.7 在 `CheckpointSnapshot.from_context` 内部实现 4 级优先级 (runtime.stopped_by → runtime.condition_eval.stopped_by → metadata.condition_eval.stopped_by → ctx.stop → "stop_flag")。如果其他 Stage 需要类似逻辑，会重复。
2. **没有 stop reason 类型化**：stopped_by 是字符串，但实际语义应该是 enum (condition / retry / timeout / cancellation / manual / hook)
3. **custom 命名空间访问不优雅**：`ctx.runtime.custom.get("my_plugin")` 暴露 dict API，没有 `ctx.runtime.get_custom("my_plugin")` 明确
4. **没有 helper for "what happened"**：消费端经常需要 "why was this stopped" / "what was the outcome" 等语义化查询
5. **类型注解不一致**：直接属性访问 mypy 提示 `Optional[T]`，但消费端经常 `assert x is not None`，没有更好的 API

### 1.2 目标

V1.0.8 引入 **Metadata Access API** — 统一访问 `RuntimeMetadata` 的接口层：

1. **5 个核心 getter** (替代散落属性访问)：
   - `get_stop_reason() -> Optional[str]`
   - `get_metrics() -> Dict[str, Any]`
   - `get_condition() -> Optional[ConditionEval]`
   - `get_plan_progress() -> Dict[str, int]`
   - `get_custom(name: str) -> Optional[Any]`

2. **1 个 resolver** (统一 stopped_by 优先级查找)：
   - `resolve_stopped_by(ctx) -> Optional[str]`
   - ChatGPT 9.88/10 Q3 采纳：封装 4 级优先级，未来 Retry/Timeout/Hook/Cancellation 复用

3. **CheckpointStage 改用 resolver** (ChatGPT 9.88/10 Q3 采纳)：
   - 移除 V1.0.7 内联优先级逻辑
   - 调用 `ctx.runtime.resolve_stopped_by(ctx)`
   - 净减代码

4. **不引入新字段**：
   - V1.0.8 不增加 RuntimeMetadata 字段
   - 仅在 `RuntimeMetadata` 类上增加方法
   - 100% 向后兼容 V1.0.7 (helper API 全部保留)

### 1.3 非目标

- ❌ **不**改 RuntimeMetadata 字段集
- ❌ **不**引入 Pydantic / dataclass 强约束
- ❌ **不**改 Stage 行为 (仅 CheckpointStage 改用 resolver)
- ❌ **不**加新 helper (set_*() 已完整)
- ❌ **不**加 deprecation 警告
- ❌ **不**做 Stage Registry (V1.0.8 ADR-0029 处理)
- ❌ **不**做 Pipeline Introspection (V1.0.8 ADR-0029 后)
- ❌ **不**做 schema_version (V1.0.8 LATER 评估)

---

## 2. 设计

### 2.1 Metadata Access API 接口

```python
# planner/runtime_metadata.py (V1.0.8 增量)

@dataclass
class RuntimeMetadata:
    # V1.0.7 字段 (不变)
    server_metrics: Dict[str, Any] = field(default_factory=dict)
    condition_eval: Optional["ConditionEval"] = None
    stopped_by: Optional[str] = None
    plan: Dict[str, int] = field(default_factory=dict)
    custom: Dict[str, Any] = field(default_factory=dict)

    # V1.0.7 helper (set_*()) — 不变
    def set_condition_eval(self, eval, *, ctx=None): ...
    def set_server_metrics(self, metrics, *, ctx=None, merge=True): ...
    def set_plan(self, plan, *, ctx=None): ...
    def set_stopped_by(self, stopped_by, *, ctx=None): ...
    def set_custom(self, key: str, value: Any) -> None: ...

    # ─────────────────────────────────────────────────────────
    # V1.0.8 新增: 5 个核心 getter (统一访问接口)
    # ─────────────────────────────────────────────────────────

    def get_stop_reason(self) -> Optional[str]:
        """获取停止原因 (顶级 stopped_by).

        Returns:
            stopped_by 字符串 (e.g. "condition:c1:skip", "retry:exhausted")
            None 表示未停止 (正常完成)
        """
        return self.stopped_by

    def get_metrics(self) -> Dict[str, Any]:
        """获取 server metrics (返回 copy 避免外部修改).

        Returns:
            server_metrics dict (默认空 dict, never None)
        """
        return dict(self.server_metrics)

    def get_condition(self) -> Optional["ConditionEval"]:
        """获取最后一次 condition eval.

        Returns:
            ConditionEval 实例 (ConditionStage 写入)
            None 表示未执行 condition
        """
        return self.condition_eval

    def get_plan_progress(self) -> Dict[str, int]:
        """获取 plan 聚合进度 (返回 copy).

        Returns:
            plan dict, e.g. {"success": 3, "failed": 1, "total": 4}
            默认空 dict
        """
        return dict(self.plan)

    def get_custom(self, name: str, default: Any = None) -> Any:
        """获取 user plugin 命名空间数据.

        Args:
            name: plugin 名称 (e.g. "my_plugin")
            default: 默认值, 找不到时返回 (默认 None)

        Returns:
            plugin 写入的数据
            未找到返回 default
        """
        return self.custom.get(name, default)

    # ─────────────────────────────────────────────────────────
    # V1.0.8 新增: resolve_stopped_by (采纳 ChatGPT 9.88/10 Q3)
    # ─────────────────────────────────────────────────────────

    def resolve_stopped_by(self, ctx: "ExecutionContext") -> Optional[str]:
        """解析 stopped_by (4 级优先级查找).

        优先级 (V1.0.7 行为, 封装到 RuntimeMetadata):
          1. ctx.runtime.stopped_by (顶级字段, V1.0.7 新 API)
          2. ctx.runtime.condition_eval.stopped_by (V1.0.7 强类型)
          3. ctx.metadata["condition_eval"]["stopped_by"] (V1.0.6 dict 兼容)
          4. ctx.stop → "stop_flag" (兜底)

        未来扩展 (V1.x / V2):
          - RetryStage: 写 ctx.runtime.stopped_by = "retry:exhausted"
          - Timeout: 写 ctx.runtime.stopped_by = "timeout:30s"
          - Cancellation: 写 ctx.runtime.stopped_by = "cancellation:user"
          - Hook: 写 ctx.runtime.stopped_by = "hook:my_hook"
          - Manual Abort: 写 ctx.runtime.stopped_by = "manual:user_id"

        Args:
            ctx: ExecutionContext (用于读取 metadata 兜底)

        Returns:
            stopped_by 字符串 或 None (未停止)
        """
        # 优先级 1: 顶级 stopped_by
        if self.stopped_by is not None:
            return self.stopped_by
        # 优先级 2: condition_eval.stopped_by
        if self.condition_eval is not None and self.condition_eval.stopped_by is not None:
            return self.condition_eval.stopped_by
        # 优先级 3: ctx.metadata["condition_eval"] dict 兜底
        ctx_metadata = getattr(ctx, "metadata", None) or {}
        if isinstance(ctx_metadata, dict):
            condition_eval = ctx_metadata.get("condition_eval")
            if isinstance(condition_eval, dict):
                stopped_by = condition_eval.get("stopped_by")
                if stopped_by:
                    return stopped_by
        # 优先级 4: ctx.stop → "stop_flag"
        if getattr(ctx, "stop", False):
            return "stop_flag"
        return None
```

### 2.2 CheckpointStage 改造 (采纳 ChatGPT 9.88/10 Q3)

```python
# planner/stages/checkpoint_stage.py (V1.0.8 改造)
class CheckpointSnapshot:
    @classmethod
    def from_context(cls, ctx, *, timestamp=None, error=None):
        # ... 省略 task_id / provider / bridge 提取 ...

        # V1.0.8: 改用 runtime.resolve_stopped_by(ctx) (净减代码)
        stopped_by = ctx.runtime.resolve_stopped_by(ctx)
        aborted = stopped_by is not None

        # V1.0.7 行为: 读 server_metrics 优先 ctx.runtime, 兜底 Result.metadata
        # V1.0.8 保持不变 (简单 getter)
        server_metrics = ctx.runtime.get_metrics() or (
            ctx.result.metadata.get("server_metrics", {})
            if ctx.result is not None and isinstance(ctx.result.metadata, dict) else {}
        )

        return cls(
            task_id=task.task_id,
            # ... 其他字段 ...
            server_metrics=server_metrics,
            snapshot_version=cls.SNAPSHOT_VERSION,
            aborted=aborted,
            stopped_by=stopped_by,
            error=error,
        )
```

**净减代码：**
- V1.0.7 CheckpointStage 优先级逻辑：~15 行 (4 个 if-elif 块)
- V1.0.8: 1 行 `stopped_by = ctx.runtime.resolve_stopped_by(ctx)`
- 净减：~14 行

### 2.3 使用示例 (V1.0.8)

```python
# 旧写法 (V1.0.7 散落属性访问)
if ctx.runtime.stopped_by:
    logger.info("Pipeline stopped: %s", ctx.runtime.stopped_by)
metrics = ctx.runtime.server_metrics or {}
condition = ctx.runtime.condition_eval
plan = ctx.runtime.plan
my_plugin_data = ctx.runtime.custom.get("my_plugin")

# 新写法 (V1.0.8 统一 getter)
reason = ctx.runtime.get_stop_reason()
if reason:
    logger.info("Pipeline stopped: %s", reason)
metrics = ctx.runtime.get_metrics()       # 永远 dict
condition = ctx.runtime.get_condition()   # Optional[ConditionEval]
plan = ctx.runtime.get_plan_progress()    # 永远 dict
my_plugin_data = ctx.runtime.get_custom("my_plugin")

# Resolver 替代散落优先级
stopped_by = ctx.runtime.resolve_stopped_by(ctx)
```

### 2.4 API 设计原则

1. **Getter 不抛异常** — 找不到时返回 None / 空 dict / default
2. **Getter 返回 copy** — `get_metrics()` / `get_plan_progress()` 返回 dict copy, 避免外部修改
3. **Getter 永远返回值** — `get_metrics()` 永远返回 dict (默认空), 不返回 None
4. **Optional type** — `get_condition()` / `get_stop_reason()` / `get_custom()` 返回 Optional, 明确"可能未设置"
5. **Resolver 是单参数** — `resolve_stopped_by(ctx)` 只接 ExecutionContext (用于 metadata 兜底), 未来扩展
6. **不引入新 metadata 字段** — V1.0.8 不加 server_metrics_extra / stopped_at 等, 保持 V1.0.7 字段集

### 2.5 向后兼容

- ✅ **100% 兼容 V1.0.7**: 旧代码 `ctx.runtime.stopped_by` / `ctx.runtime.server_metrics` 仍工作
- ✅ **旧 helper 保留**: `set_condition_eval()` / `set_server_metrics()` 等不变
- ✅ **CheckpointStage 行为不变**: resolve_stopped_by 封装 V1.0.7 同样的 4 级优先级
- ✅ **第三方 Stage 不感知 V1.0.8**: V1.0.8 仅在 RuntimeMetadata 加方法, 不改字段

---

## 3. 关键决策

### 3.1 为什么 getter 返回 copy？

- ✅ 防止外部修改污染 runtime (防御性拷贝)
- ✅ 避免消费者误以为修改 dict 会传播到 runtime
- ✅ V1.0.7 helper.set_server_metrics 写时合并, 读时也应 copy
- ❌ 性能开销可忽略 (dict copy 是 O(n), n 通常 < 100)

### 3.2 为什么 getter 不抛异常？

- ✅ Runtime access 是"软查询", 不应中断 Pipeline
- ✅ 缺失数据 = 未执行该 Stage, 这是正常状态
- ✅ 消费端 `if x is not None` 比 `try/except KeyError` 优雅
- ❌ 抛异常 = 强制消费端写 try/except, 增加复杂度

### 3.3 为什么 `resolve_stopped_by` 接收 `ctx` 参数？

- ✅ 优先级 3 需要读 `ctx.metadata` (V1.0.6 dict 兼容)
- ✅ 未来 Retry / Timeout / Cancellation 写 `ctx.runtime.stopped_by` 后, 优先级 1 自动命中
- ❌ 不接 ctx = 无法回退到 dict 兜底
- 选择：让 resolver 知道 ctx, 但**不**修改 ctx (resolver 是 read-only)

### 3.4 为什么 V1.0.8 不引入 schema_version？

- 采纳 ChatGPT 9.85/10 Defer 建议: "V1.0.7 不要加, V1.0.8 评估"
- 当前 V1.0.7 RuntimeMetadata 字段集稳定, schema_version = 1 隐含
- V1.0.8 加 schema_version 但不真用, 反而引入 dead field
- V1.0.8 实际加 schema_version 的时机: 当字段集真要变化时
- V1.0.8 **不**加 schema_version

### 3.5 为什么 `get_custom(name)` 接 `default` 参数？

- ✅ 第三方 Plugin 标准用法: `get_custom("my_plugin")` 返回 None, 显式 `get_custom("my_plugin", {})` 返回 `{}`
- ✅ 比 `custom.get(name)` 或 `custom.get(name, default)` 更明确
- ✅ API 表面统一 (其他 getter 也有 default 语义)

### 3.6 为什么 V1.0.8 不引入 stop reason enum？

- ❌ stopped_by 当前是字符串 (e.g. "condition:c1:skip"), 灵活但 type unsafe
- ❌ 引入 enum 需列出所有可能值, V1.0.8 只有 ConditionStage 写, 未来 Retry/Timeout 才知道
- ✅ V1.0.8 保持字符串 (简单), V2 评估 enum
- 关键: 字符串已经携带 namespace (e.g. "condition:" / "retry:" / "timeout:"), 消费端可以 prefix 匹配

### 3.7 为什么 V1.0.8 不改 Stage behavior？

- ✅ V1.0.7 Stage 已经 Accepted, 不破坏
- ✅ V1.0.8 仅 CheckpointStage 改用 resolver (净减代码, 行为不变)
- ✅ 其他 Stage 暂不改, V1.0.9 评估

---

## 4. 替代方案

### 4.1 替代 1：仅文档化 (不加 getter)

- ❌ 散落属性访问不优雅
- ❌ 重复优先级逻辑
- ❌ 文档化弱约束
- **结论：reject**

### 4.2 替代 2：用 Pydantic BaseModel

- ❌ 引入外部依赖
- ❌ V1.0.x 范围内过度工程
- **结论：defer（V2 评估）**

### 4.3 替代 3：全部引入 enum stop reason

- ❌ V1.0.8 只有 ConditionStage 写, enum 字段不完整
- ❌ 未来 Retry/Timeout 写时 enum 不够
- **结论：defer（V2 评估）**

### 4.4 替代 4：本次采纳 (5 getter + 1 resolver + CheckpointStage 改造)

- ✅ 简单、聚焦、净减代码
- ✅ 100% 向后兼容 V1.0.7
- ✅ 复用 ChatGPT 9.88/10 Q3 resolver 建议
- **结论：adopt**

### 4.5 替代 5：getter 全部返回 Optional[T] (统一 Optional 风格)

- ❌ `get_metrics()` 永远返回 dict (默认空), 用 Optional[Dict] 反而语义错误
- ❌ 消费端 `metrics = get_metrics() or {}` 冗余
- **结论：reject — 当前设计区分"永远返回"vs"可选返回"更准确**

---

## 5. 影响范围

### 5.1 改动文件

| 文件 | 改动 |
|------|------|
| `planner/runtime_metadata.py` | 新增 6 个方法 (5 getter + 1 resolver) |
| `planner/stages/checkpoint_stage.py` | 改用 `runtime.resolve_stopped_by(ctx)` 替代内联优先级 (净减 ~14 行) |
| `tests/test_runtime_metadata.py` | 增量测试 6 个新方法 (15+ tests) |
| `tests/test_checkpoint_stage.py` | 增量测试 resolver 调用 (3+ tests) |
| `docs/runtime-contract.md` | §11 Metadata Access API (待写) |

### 5.2 兼容性

- ✅ **零 Breaking Change**: V1.0.7 所有属性访问、helper 调用都保留
- ✅ 第三方 Stage / Hook 不感知 V1.0.8
- ✅ V1.0.7 全部 75 个测试无需修改
- ✅ 目标：V1.0.8 共 90+ 测试, 全部通过

### 5.3 Core Freeze 影响

- ❌ **不**改 `core/` 下任何文件
- ❌ **不**改 `router/router.py`
- ❌ **不**改 `providers/`
- ✅ 仅 `planner/` 内扩展

---

## 6. 测试策略

### 6.1 Getter 单元测试 (15+, 采纳 5 个 getter)

- `test_get_stop_reason_returns_top_level` — get_stop_reason 返回 runtime.stopped_by
- `test_get_stop_reason_returns_none_when_not_stopped` — 未停止返回 None
- `test_get_metrics_returns_dict_copy` — get_metrics 返回 copy (不共享引用)
- `test_get_metrics_default_empty_dict` — 默认返回空 dict
- `test_get_condition_returns_eval_or_none` — get_condition 返回 ConditionEval 或 None
- `test_get_plan_progress_returns_dict_copy` — get_plan_progress 返回 copy
- `test_get_plan_progress_default_empty_dict` — 默认返回空 dict
- `test_get_custom_returns_plugin_data` — get_custom("my_plugin") 返回数据
- `test_get_custom_returns_default_when_missing` — 未找到返回 default
- `test_get_custom_default_none` — default 默认 None
- `test_getters_return_independent_copies` — 多个 getter 调用结果独立
- `test_getter_does_not_modify_runtime` — getter 不修改 runtime 状态
- `test_get_metrics_with_populated_runtime` — runtime 有数据时 get_metrics 返回
- `test_get_plan_progress_with_populated_runtime` — runtime 有数据时 get_plan_progress 返回
- `test_get_condition_with_populated_runtime` — runtime 有数据时 get_condition 返回

### 6.2 Resolver 单元测试 (6+)

- `test_resolve_stopped_by_prefers_top_level` — 优先级 1: runtime.stopped_by
- `test_resolve_stopped_by_falls_back_to_condition_eval` — 优先级 2: runtime.condition_eval.stopped_by
- `test_resolve_stopped_by_falls_back_to_metadata_dict` — 优先级 3: ctx.metadata["condition_eval"]
- `test_resolve_stopped_by_falls_back_to_stop_flag` — 优先级 4: ctx.stop → "stop_flag"
- `test_resolve_stopped_by_returns_none_when_no_stop` — 未停止返回 None
- `test_resolve_stopped_by_priority_order` — 优先级顺序测试

### 6.3 CheckpointStage 集成测试 (3+)

- `test_checkpoint_uses_resolve_stopped_by` — CheckpointStage 改用 resolver
- `test_checkpoint_behavior_unchanged_from_v107` — V1.0.7 行为完全保留
- `test_checkpoint_net_code_reduction` — 检查 CheckpointStage 代码净减

### 6.4 兼容性测试 (3+)

- `test_v107_property_access_still_works` — `ctx.runtime.stopped_by` 仍工作
- `test_v107_helper_calls_still_work` — `set_condition_eval()` 仍工作
- `test_v107_third_party_plugin_dict_still_works` — V1.0.6 Plugin dict 仍工作

### 6.5 V1.0.x 回归测试

- ✅ V1.0.7 全部 75 个测试无需修改
- ✅ 目标：V1.0.8 共 90+ 新增测试, 全部通过

---

## 7. 实施计划

### 7.1 阶段 1: Getter + Resolver (Day 1)

- `planner/runtime_metadata.py` 新增 6 个方法
- 21+ 单元测试通过

### 7.2 阶段 2: CheckpointStage 改造 (Day 1)

- 改用 `runtime.resolve_stopped_by(ctx)`
- 净减 ~14 行
- 3+ 集成测试

### 7.3 阶段 3: 兼容性验证 (Day 1-2)

- 3+ 兼容性测试
- V1.0.7 全量回归

### 7.4 阶段 4: 全量回归 (Day 2)

- V1.0.x 全量测试 (265+ tests)
- Runtime Contract §11 同步
- ChatGPT 代码审核
- ADR-0028 Accepted

### 7.5 阶段 5: V1.0.8 ADR-0029 Stage Registry 启动 (Day 2-3)

- ChatGPT 9.88/10 路线图: V1.0.8 MUST
- StageDescriptor 注册 / 生命周期查询 / 能力索引

---

## 8. ChatGPT 审核请求

> **本 ADR V1.0.8 关键设计：**
>
> 1. **5 个核心 getter + 1 个 resolver** (采纳 ChatGPT 9.88/10 Q3 关键建议)
> 2. **CheckpointStage 改用 resolver** (净减 ~14 行, 行为完全不变)
> 3. **不引入新字段** (V1.0.8 字段集与 V1.0.7 相同)
> 4. **不引入 schema_version** (采纳 ChatGPT 9.85/10 Defer)
> 5. **不引入 stop reason enum** (字符串已经携带 namespace, 未来 V2 评估)
> 6. **100% 向后兼容** (V1.0.7 全部 API 保留)

**8 个具体问题：**

1. **Getter 设计正确？** 5 个 getter (`get_stop_reason` / `get_metrics` / `get_condition` / `get_plan_progress` / `get_custom`) + 1 个 resolver (`resolve_stopped_by`)。是否完整？是否需要 `get_all()` 之类的批量接口？

2. **Getter 返回 copy 合理？** `get_metrics()` / `get_plan_progress()` 返回 dict copy (防御性拷贝)。`get_custom()` 返回引用 (允许修改)。是否一致？`get_metrics()` 也返回引用会更高效吗？

3. **Resolver 接收 ctx 参数？** `resolve_stopped_by(ctx)` 接 ctx 用于 metadata 兜底。是否应该改成"ctx 是可选"（多数情况不需要 dict 兜底）？还是保持必填？

4. **CheckpointStage 净减代码足够？** V1.0.7 CheckpointStage 内联优先级 ~15 行 → V1.0.8 改用 resolver 1 行, 净减 ~14 行。是否还应进一步提取（如 get_server_metrics_or_fallback）？

5. **Stop reason 不引入 enum？** V1.0.8 保持字符串 (e.g. "condition:c1:skip", "retry:exhausted")。V1.0.8 字段集稳定, enum 收益有限。V2 评估？

6. **不引入 schema_version？** 采纳 ChatGPT 9.85/10 Defer, V1.0.8 字段集不变 → 不加 schema_version。如果未来 V1.0.9 真要加字段, 应该 V1.0.9 加还是 V1.0.8 现在加？

7. **不引入 Stage Registry API？** 采纳 ChatGPT 9.88/10 路线图, Stage Registry 是 V1.0.8 ADR-0029 (独立 ADR)。本 ADR 只做 Metadata Access API。scope 是否合理？

8. **V1.0.8 完整路线图**：采纳 ChatGPT 9.88/10 Q8, V1.0.8 MUST = Metadata Access API + Stage Registry。两者是独立 ADR 还是合并 ADR? 哪个先做？

**期望评分：9.5+/10** (V1.0.7 ADR 是 9.85/10, V1.0.8 是更小的聚焦 ADR)

---

## 9. V1.0.7 → V1.0.8 演化图

```
V1.0.7 (V1.0.7 Accepted 9.88/10):
  ctx.runtime = RuntimeMetadata()
  ctx.runtime.stopped_by = "condition:c1:skip"  # 直读
  ctx.runtime.server_metrics = {...}  # 直读
  # CheckpointStage 内联 4 级优先级逻辑 (~15 行)

V1.0.8 (本 ADR):
  ctx.runtime.get_stop_reason()  # 统一 getter
  ctx.runtime.get_metrics()  # 返回 copy
  ctx.runtime.get_condition()
  ctx.runtime.get_plan_progress()
  ctx.runtime.get_custom("my_plugin")
  ctx.runtime.resolve_stopped_by(ctx)  # 封装 4 级优先级
  # CheckpointStage 改用 resolver (净减 ~14 行)
```

**关键演进：**
- 直读 → 统一 getter (API 表面一致)
- 散落优先级 → resolver (复用, 未来扩展)
- 防御性 copy (防止外部污染)
- CheckpointStage 净减 ~14 行

---

## 10. 关联

- **前序**: [ADR-0027 RuntimeMetadata](0027-runtime-metadata-schema.md) (V1.0.7 Accepted 9.88/10)
- **后续**: V1.0.8 ADR-0029 Stage Registry / Pipeline Introspection / Schema Versioning
- **V2 路线**: Pydantic schema validation / stop reason enum / metadata 正式字段化
- **Runtime Contract**: §11 (待写)
- **ARCHITECTURE**: §2.3 V1.0 路线 (Runtime Observability)
- **ChatGPT 路线图**: V1.0.7 代码审核 9.88/10 Q8 "V1.0.8: Metadata Access API (MUST)"
