# DESIGN.md
## AI Hub — 设计决策记录

> 版本：v0.0
> 日期：2026-07-10
> 状态：活跃

---

## 1. 为什么叫 "AI Hub"？

项目最初候选名称包括 FreeHub AI、QuotaHub、AIPool、OneAI Hub 等。

最终选择 "AI Hub" 是因为：
- 简短，好记，好搜索
- "Hub" 准确描述了聚合入口的定位
- 不绑定特定卖点（免费额度聚合是 V0.1 的卖点，但不是项目的永久定义）

对外定位口号：**One command. Multiple providers. Free-first routing.**

---

## 2. 为什么第一版用规则路由而不是 AI 路由？

| 方案 | 优点 | 缺点 |
|------|------|------|
| 规则路由（if-else + 关键词） | 简单可控、无额外成本、可调试 | 准确率有限、需要手动维护关键词 |
| AI 路由（LLM 分类） | 准确率高、支持模糊意图 | 有成本、有延迟、依赖 LLM 可用性 |

**决策**：第一版用规则路由。

**理由**：
1. 第一版目标是验证"聚合入口"是否有用，不是验证"路由有多智能"
2. 规则路由零成本、零延迟、可预测
3. 用户的路由错误反馈可以直接转化为新增关键词，迭代成本低
4. V0.3 升级 AI 路由时，Router 内部替换即可，Provider 接口和 Result 格式不变

**升级触发条件**：用户反馈"路由选错了"超过每周 3 次。

---

## 3. 为什么 Provider 接口只有 4 个必须实现的方法？

```
health()         → 服务是否在线
authenticated()  → 用户是否已登录
quota_left()     → 剩余免费额度
execute(task)    → 执行任务
```

**决策依据**：

| 考虑过的接口 | 是否采用 | 理由 |
|-------------|---------|------|
| `health()` | ✅ | Router 需要知道 Provider 是否可用 |
| `authenticated()` | ✅ | 很多平台需要登录才能使用免费额度 |
| `quota_left()` | ✅ | 核心卖点——优先使用免费额度 |
| `execute(task)` | ✅ | 核心功能——执行任务 |
| `supports(type)` | 预留 | V0.3 AI Router 用，第一版用 task_types 属性代替 |
| `cost()` | 预留 | V0.5 成本优化路由用 |
| `stream(task)` | ❌ | 第一版不做流式输出，复杂度太高 |
| `cancel(task_id)` | ❌ | 第一版不支持取消 |
| `retry(task)` | ❌ | 由 Router 的 Fallback 机制代替 |

**核心原则**：接口越少越稳定。能不加的就不加。需要时再加，带默认值。

---

## 4. 为什么 Result 用 dataclass 而不是 Pydantic model？

| 方案 | 优点 | 缺点 |
|------|------|------|
| dataclass | 标准库、零依赖、简单 | 无自动验证（需要手动 __post_init__） |
| Pydantic | 自动类型验证、JSON 序列化好 | 额外依赖、V2 API 变化大 |

**决策**：用 dataclass。

**理由**：
1. 第一版 Result 只有 5 个字段，手动验证足够
2. 不引入额外依赖，降低安装门槛
3. V0.5 如果需要更复杂的验证，可以迁移到 Pydantic，接口不变

---

## 5. 为什么用 JSONL 存历史记录而不是 SQLite？

| 方案 | 优点 | 缺点 |
|------|------|------|
| JSONL 文件 | 零依赖、可读、追加写入快 | 查询能力弱、文件大了会慢 |
| SQLite | 查询强、索引快 | 需要 sql 模块（标准库但有额外复杂度） |

**决策**：第一版用 JSONL，V0.5 换 SQLite。

**理由**：
1. 第一版历史记录量小（个人使用，每天几十条）
2. JSONL 可以直接 `cat` 查看，调试方便
3. 迁移到 SQLite 只需要改 HistoryStore 类内部实现，接口不变

---

## 6. 为什么不用 Agent 这个词？

在 PRODUCT.md 和 PROVIDER_SPEC.md 中，我们刻意使用 "Provider" 而不是 "Agent"。

**理由**：
1. V0.1~V0.3 阶段，每个平台只是一个"能力提供者"，没有自主决策能力
2. "Agent" 暗示了自主性、规划能力、多步推理，但第一版只是 One Task → One Provider
3. V1.0 启用 Agent 编排时，Agent 是 Provider 的超集——`Agent.run(task)` 兼容 `Provider.execute(task)`
4. 避免给用户和贡献者造成"这是一个 Agent 框架"的错误预期

**演进路径**：
```
V0.1: Provider（能力提供者）
V0.5: Provider + Task Splitter（任务分解器）
V1.0: Agent（= Provider + 规划 + 上下文 + 协同）
V2.0: Plugin（= Agent + 动态加载 + 社区分发）
```

---

## 7. 为什么不集成飞书？

在之前的 v2.0 提示词模板中，飞书被设计为独立的交付层（通过 Lark CLI）。

**决策**：V0.1~V0.5 不集成飞书。V1.0 才集成。

**理由**：
1. 第一版面向个人开发者，不需要团队协作
2. 飞书集成需要额外的 Lark CLI 安装和配置，增加使用门槛
3. 飞书交付是"编排"阶段的需求，不是"聚合"阶段的需求
4. V1.0 集成时，飞书是一个独立的 Deliver 层，不影响 Provider 和 Router

---

## 8. 为什么先接入 QODER、Gemini CLI、QClaw 这三个？

| Provider | 选择理由 | 任务类型 |
|----------|---------|---------|
| QODER | 编程是最高频的 AI 任务，QODER 有免费额度 | coding |
| Gemini CLI | 免费、通用能力强、覆盖搜索和通用任务 | search, general |
| QClaw | 分析和文件操作，本地已安装 | analysis, file_ops |

**接入顺序**严格按 ROADMAP.md V0.1 的开发顺序：先 QODER → 再 Gemini → 最后 QClaw。一次只接一个，出问题好定位。

---

## 9. 为什么预留 supports() 和 cost() 但不用？

这两个接口在第一版定义但不用。

**supports(task_type)**：
- 第一版用 `task_types` 类属性代替（Router 直接检查列表）
- V0.3 的 AI Router 需要更细粒度的能力判断，会调用此方法
- 现在定义好，未来不用改 Provider 接口

**cost()**：
- 第一版所有 Provider 都是免费的，cost 没有意义
- V0.5+ 引入付费 API 时，Router 可以基于成本做优化
- 现在定义好，未来不用改 Provider 接口

**核心思想**：接口一次定义、长期不变。实现可以后补。

---

## 10. 为什么 CLI 用 python -m 而不是直接 ai-hub 命令？

第一版用 `python -m cli.main` 启动，不打包为可执行命令。

**理由**：
1. 开发阶段频繁迭代，`python -m` 不需要重新安装
2. V0.2 通过 `pyproject.toml` 的 `[project.scripts]` 注册 `ai-hub` 命令
3. 不影响功能验证

---

## 变更记录

| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-07-10 | 初始设计决策 | V0.0 Skeleton |
