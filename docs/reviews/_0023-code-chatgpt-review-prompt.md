# ChatGPT 代码层审核 prompt — ADR-0023 V1.0.3 CheckpointStage 实施

## 背景

ai-hub 项目 V1.0.3 CheckpointStage 实施已完成，请审核代码质量与 ADR 的一致性。

- **ADR**: [0023-checkpoint-stage.md](https://...) (9.9/10 FINAL APPROVED)
- **前序 ChatGPT 路线图**: V1.0.2 代码审核 9.95/10 — "V1.0.3 CheckpointStage, **不要加入 Retry 改动**"
- **实施 commit**: c650612 "feat: V1.0.3 CheckpointStage 实施"
- **测试基线**: 245 passed, 0 failed (V1.0.2 196 + V1.0.3 21 + sqlite_execution_store 28)

## 实施范围（7 个文件，975 行新增）

### 新增
- `planner/execution_store.py` (~60 lines): ExecutionStore Protocol 抽象
- `planner/stages/checkpoint_stage.py` (~240 lines): CheckpointStage + CheckpointSnapshot
- `tests/test_checkpoint_stage.py` (21 tests, 7 个测试类)

### 修改
- `planner/sqlite_execution_store.py` (+ append() 方法, handle() 委托)
- `planner/stages/__init__.py` (导出 CheckpointStage)
- `planner/pipeline.py` (default_pipeline 工厂加 2 参数, 主体 0 行为变化)
- `planner/executor.py` (PlanExecutor 透传, 主体 0 行为变化)

## 关键设计

### 1. ExecutionStore Protocol 抽象 (ChatGPT 9.9/10 Q2 关键采纳)

```python
# planner/execution_store.py
@runtime_checkable
class ExecutionStore(Protocol):
    """ExecutionStore Protocol (V1.0.3).

    Contract (from Runtime Contract "Storage is Disposable"):
    - MUST accept ExecutionEvent
    - MUST NOT raise exception (Best Effort)
    - Storage Failure MUST NOT break Execution
    """
    def append(self, event: ExecutionEvent) -> None: ...
```

**为什么不绑 SQLite** (ChatGPT 关键建议):
- Runtime Contract: "Storage is Disposable"
- 未来可换 Memory / Remote / S3 实现
- CheckpointStage 接受 Protocol，运行时传 SQLiteExecutionStore()

### 2. CheckpointSnapshot — Runtime Projection

```python
# planner/stages/checkpoint_stage.py
@dataclass
class CheckpointSnapshot:
    task_id: str
    stage: str  # "checkpoint"
    timestamp: float
    task_content: str
    task_capabilities: list
    provider_name: str       # str, NOT provider object
    bridge_name: str         # str (class name), NOT bridge object
    bridge_result_success: bool
    bridge_result_output: str
    bridge_result_error: Optional[str]
    bridge_result_duration_ms: int
    bridge_result_artifacts: list
    server_metrics: dict     # 提取自 Result.metadata
    error: Optional[str] = None

    @classmethod
    def from_context(cls, ctx, timestamp=None, error=None) -> "CheckpointSnapshot":
        """主动挑选关键字段 (不 pickle 整个 ctx)."""
        ...
```

**关键不变量** (ChatGPT 9.9/10 §2.4):
- Snapshot 是 Runtime Projection, 不是 ExecutionContext Serialization
- MUST NOT serialize Runtime Object
- bridge_name 仅存类名, provider_name 仅存 name

### 3. CheckpointStage — Runtime Stage

```python
class CheckpointStage:
    def __init__(self, store: ExecutionStore):
        if store is None:
            raise ValueError(...)
        self.store = store
        self._name = "checkpoint"

    def __call__(self, ctx: ExecutionContext) -> ExecutionContext:
        # 短路: ctx.stop / task=None / bridge_result=None
        if ctx.stop or ctx.task is None or ctx.bridge_result is None:
            return ctx

        # 构造快照 (失败 → pass)
        try:
            snapshot = CheckpointSnapshot.from_context(ctx)
        except Exception as e:
            logger.warning(...)
            return ctx  # Best Effort

        # 写 ExecutionStore (失败 → pass)
        try:
            event = ExecutionEvent(
                event_id=uuid.uuid4().hex,
                type="checkpoint",
                plan_id=ctx.task.task_id,
                provider=snapshot.provider_name,
                latency_ms=snapshot.bridge_result_duration_ms,
                data=snapshot.to_dict(),
            )
            self.store.append(event)
        except Exception as e:
            logger.warning(...)  # Best Effort

        return ctx  # 0 修改 ctx
```

### 4. SQLiteExecutionStore.append() — Best Effort 实现

```python
# planner/sqlite_execution_store.py
def handle(self, event: ExecutionEvent) -> None:
    # V1.0.3: 委托给 append() (向后兼容)
    self.append(event)

def append(self, event: ExecutionEvent) -> None:
    """V1.0.3 新增: ExecutionStore Protocol append 实现.

    Best Effort: 失败 logger.error / warning, 不抛异常.
    """
    try:
        self._conn.execute(
            "INSERT INTO execution_events ... VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event.event_id, event.type, event.plan_id, ...),
        )
        self._conn.commit()
    except sqlite3.IntegrityError as e:
        _log.warning("duplicate event_id=%s: %s", event.event_id, e)
    except sqlite3.DatabaseError as e:
        _log.error("append failed: %s", e)
```

### 5. Stage 顺序

```python
# planner/pipeline.py default_pipeline
post_bridge = []
if include_retry:
    post_bridge.append(RetryStage())
if include_metrics:
    post_bridge.append(MetricsStage())
if include_checkpoint:
    if execution_store is None:
        raise ValueError("include_checkpoint=True requires execution_store")
    post_bridge.append(CheckpointStage(execution_store))  # 在最末
# [RetryStage, MetricsStage, CheckpointStage]
```

### 6. 关键约束 (Runtime Contract §9.1.4)

- MUST NOT 修改 ExecutionContext (仅写存储)
- MUST 写快照到 ExecutionStore (抽象)
- MUST NOT 抛异常 (Best Effort)
- MUST 仅快照 ctx 关键字段 (不存整个 ctx)
- MUST NOT serialize Runtime Object (Provider/Bridge/Router/ExecutionContext/Callable/FileHandle)
- MUST 写 type="checkpoint" (与 EventBus 统一)
- SHOULD 在最末
- SHOULD be replayable (为 V1.x Resume 留接口)

### 7. Best Effort 原则 (ChatGPT 9.9/10)

> Execution 成功 → Checkpoint 写失败 → warning → Execution 仍 Success
> 不允许: Execution → Checkpoint Exception → Pipeline FAIL

## 测试覆盖 (21 tests, 7 类)

- TestCheckpointSnapshot (3): 构造 / JSON 友好 / 关键字段非对象
- TestCheckpointStageBasics (4): store=None 报错 / task=None 短路 / bridge_result=None 短路 / name 属性
- TestCheckpointStageSQLite (3): 写 event / JSON payload / 多次写
- TestCheckpointStageIntegration (3): Stage 顺序 / 不改 ctx / +Metrics 集成
- TestCheckpointStageFailureHandling (2): 写失败不抛 / 构造失败不抛
- **TestCheckpointStageChatGPTEdgeCases (6)** (ChatGPT 9.9/10 Q8 建议补充):
  - test_failed_bridge_result_also_checkpointed
  - test_store_exception_does_not_break_pipeline
  - test_empty_output_serialization
  - test_artifacts_does_not_modify_original
  - test_none_server_metrics_becomes_empty_dict
  - test_snapshot_json_round_trip

## 关键不变量 (来自 Runtime Contract §9.1.4)

- CheckpointStage MUST NOT 修改 ExecutionContext
- CheckpointStage MUST 写快照到 ExecutionStore
- CheckpointStage MUST NOT 抛异常 (Best Effort)
- CheckpointStage MUST 仅快照 ctx 关键字段
- CheckpointStage MUST NOT serialize Runtime Object
- CheckpointStage MUST 写 type="checkpoint"
- CheckpointStage SHOULD 在最末
- CheckpointStage SHOULD be replayable

## 关键发现 / 微调说明

- ExecutionEvent 在 `planner/execution_event.py` (非 core/)，字段用 `type` (非 `event_type`)，按 Runtime Contract V0.9.4
- 复用 V0.9.5 SQLiteExecutionStore schema (execution_events 表)，不新建表
- SQLiteExecutionStore.append() 加 1 个方法，handle() 委托 (向后兼容)
- 0 修改 Pipeline 主体 (仅 default_pipeline 工厂加 2 参数)
- Core Freeze 严格: core/ + router/router.py + providers/ 0 修改

## 审核问题

1. **架构正确性**: CheckpointStage 是否真正符合 Stage 接口？0 修改 Pipeline 主体（仅 default_pipeline 工厂加 2 参数）是否做到？
2. **ExecutionStore 抽象**: Protocol 设计是否合理？@runtime_checkable 是否合适？未来 Memory/Remote/S3 实现接口是否完整？
3. **Snapshot 设计**: 仅关键字段（不存整个 ctx）是否合理？bridge_name 仅存类名是否足够？server_metrics 仅 dict 提取是否会漏信息？
4. **Stage 顺序**: [Retry, Metrics, Checkpoint] 中 Checkpoint 在最末，确保 metrics 在 checkpoint 前注入。是否需要更精细的"每个 stage 后 checkpoint"模式？
5. **失败处理**: Best Effort (写失败 → pass) 是否符合 ChatGPT Q7 建议？是否需要把"checkpoint 失败"作为 metric 暴露？
6. **Core Freeze**: 0 修改 core/ + router/ + providers/ 是否做到？planner/sqlite_execution_store.py 加 append() 是否破坏 V0.9.5 兼容性？
7. **Type 字段名**: ExecutionEvent.type (非 event_type) 是 V0.9.4 历史决定，不改 V0.9.5 schema 兼容是否合理？
8. **测试策略**: 21 tests (snapshot/basics/sqlite/integration/failure/chatgpt-edges) 是否足够？是否遗漏边界（如 ctx.result 为 None + bridge 为 None、MultipleProvider + Checkpoint 等）？
9. **Runtime Contract §9.1.4 实施**: 7 MUST + 3 SHOULD 是否全部实施？是否漏掉关键约束？
10. **JSON 序列化安全性**: raw 不可序列化时记录类型名 + 截断输出。V1.0.3 是否需要这个保护（当前默认不存 raw）？

## 期望

- 评分 ≥ 9.5/10
- 重点关注 #2 (ExecutionStore 抽象) 和 #6 (Core Freeze) 的合理性
- 任何调整建议都应说明：是否阻塞代码合并（如不阻塞，标记为"非阻塞 / V1.x 评估"）

请给出最终评分和具体调整建议。
