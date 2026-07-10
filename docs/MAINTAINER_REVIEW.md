# Maintainer Review

> **视角**: 开源项目 Maintainer
> **日期**: 2026-07-11
> **评审对象**: ai-hub V0.1.2（GitHub: icacaca-afk/ai-hub）
> **状态**: Draft

---

## 1. 未来一年路线是否合理？

### 1.1 当前 Roadmap

| 版本 | 目标 | 成功标准 |
|------|------|---------|
| V0.0.6 ✅ | 接口冻结 | 12 测试 + 4 Provider Validation |
| V0.1 ✅ | 3 个真实 Provider | CLI + API 零修改 core/ |
| V0.2 | 额度管理 | Quota Manager + 自动切换 |
| V0.3 | AI 智能路由 + GUIBridge | LLM 分类 + GUI Provider |
| V0.5 | 任务分解 | 多步任务自动拆分 |
| V1.0 | Agent 编排 | 多 Provider 协同 + 飞书交付 |
| V2.0 | 插件生态 | 社区贡献 Provider |

### 1.2 评价

**合理的部分**:
- V0.0 → V0.1 → V0.2 的渐进路线是对的。先证明架构可扩展，再加横切关注点
- 接口冻结在 V0.0.6 做得太对了。没有冻结就没有"零修改"的可验证承诺
- Bridge 类型分阶段实现（CLI → API → GUI → Browser）是对的，复杂度递增

**值得商榷的部分**:

| 路线 | 问题 | 建议 |
|------|------|------|
| V0.3 AI 智能路由 + GUIBridge 同一版本 | 两件不相关的事绑在一起 | 拆分：V0.3 只做 GUIBridge，V0.4 做 AI 路由 |
| V0.5 任务分解 | 跨度太大（从 V0.3 到 V0.5 中间没有过渡） | V0.4 做异步执行（非阻塞 run()），为任务分解铺路 |
| V1.0 Agent 编排 + 飞书交付 | 飞书是特定平台的交付层，不应硬编码到 V1.0 目标 | V1.0 只做 Agent 编排，飞书作为可选插件 |
| V2.0 插件生态 | 目标太模糊 | 定义清楚：Provider 热加载？主题插件？钩子？ |

**总体判断**: 路线方向对，但 V0.3 之后需要细化。

---

## 2. 哪些地方容易过度设计？

### 2.1 QuotaManager（V0.2 风险区）

**过度设计信号**:
- 为"未来可能的多用户场景"设计 quota 隔离 → 当前只有一个用户
- 为"按 token 计费"设计精确成本追踪 → 当前 Provider 都不返回 token 用量
- 为"quota 重置策略"设计可配置规则 → 当前只有 daily / unlimited 两种

**建议**: V0.2 的 QuotaManager 只需要 3 个方法：`is_available(name)`, `consume(name)`, `remaining(name)`。其余全部 YAGNI。

### 2.2 Capability 系统

**过度设计信号**:
- `capabilities.py` 中的 `KEYWORD_TO_CAPABILITY` 映射表已经有很多关键词
- 一个关键词映射到多个 capability（如 "pdf" → ["text.summarize", "text.analyze"]）
- V0.3 要用 AI 分类替代关键词——但关键词其实够用

**建议**: 不要急于上 AI 路由。关键词 + 人工 fallback 在 V0.5 之前都够用。AI 路由引入的 LLM 调用延迟和成本可能不值得。

### 2.3 ProviderMetadata 字段过多

当前 ProviderMetadata 有 12 个字段。其中：

| 字段 | 是否必要 | 备注 |
|------|---------|------|
| name | ✅ | 核心 |
| display_name | ✅ | 核心 |
| description | ✅ | 核心 |
| version | ✅ | 核心 |
| capabilities | ✅ | 核心 |
| priority | ✅ | 核心 |
| fallback | ✅ | 核心 |
| quota_type | ✅ | V0.2 需要 |
| quota_total | ✅ | V0.2 需要 |
| quota_auto_detect | ⚠️ | 没有实现自动检测 |
| cost_currency | ⚠️ | 没有实现成本计算 |
| cost_amount | ⚠️ | 没有实现成本计算 |
| cost_unit | ⚠️ | 没有实现成本计算 |

**建议**: cost 相关的 3 个字段是预留字段，没有实现。不要在 V0.5 之前加任何 cost 逻辑。如果 V1.0 还不需要，考虑从 Stable 接口中标记为 Deprecated。

### 2.4 Bridge 类型预留

当前定义了 5 种 Bridge：Fake / CLI / API / GUI / Browser。

**过度设计信号**:
- GUIBridge 和 BrowserBridge 的 `run()` 都返回 not implemented
- 它们占了 `bridge.py` 中 30% 的代码，但没有任何功能

**建议**: 保留预留接口是对的（外部开发者能看到"未来会有"），但不要在 V0.5 之前给它们加任何实现逻辑。当前的最小桩就够了。

---

## 3. 哪些地方以后一定会成为技术债？

### 3.1 🔴 关键词路由的精确性问题

当前 `classify()` 用 `if keyword in task_lower` 做匹配。

**问题**:
- "写一个 Python 脚本部署到服务器" → 匹配 "写一个" → code.generate ✅
- "帮我看看这个 bug 是不是 Python 版本问题" → 匹配 "bug" → code.debug，但用户可能想要 general.chat
- "搜索 Python 异步编程的最佳实践" → 匹配 "搜索" + "python" → search.web + code.generate，但用户只想要搜索

**技术债触发点**: 当 Provider 数量超过 10 个时，关键词误路由会变成用户可感知的问题。

**建议**: V0.3 做 AI 路由时，保留关键词作为 fallback（AI 分类失败时用关键词）。不要试图让关键词覆盖所有 case。

### 3.2 🔴 Router.execute() 的同步阻塞

`router.execute()` 是同步的——调用 `bridge.run()` 后阻塞直到完成。

**问题**:
- CLI Provider 超时 300s → 用户等 5 分钟
- 无法取消正在执行的任务
- 无法同时执行多个 Task（如任务分解场景）

**技术债触发点**: V0.5 任务分解时，需要并行执行子任务。同步 Router 无法支持。

**建议**: V0.4 引入 `router.execute_async()` 方法（返回 Future），与 `execute()` 并存。不改 `execute()` 签名（Stable 承诺）。

### 3.3 🟡 CLI 命令注入风险

CLIBridge 的 `run()` 中：

```python
safe_content = task.content.replace('"', '\\"')
full_cmd = cmd_template.format(task=safe_content)
subprocess.run(full_cmd, shell=True, ...)
```

`shell=True` + 用户输入 = 潜在的命令注入。

**问题**:
- 虽然转义了双引号，但 `$()` / `` ` `` / `&` / `|` 等-shell 特殊字符没有被处理
- 如果 task.content 包含 `"; rm -rf /; "`，转义后是 `\"; rm -rf /; \"`——在 shell 中仍然可能被执行

**技术债触发点**: 当 ai-hub 被部署为 Web 服务（接收外部输入）时，这是安全漏洞。

**建议**: V0.2 改用 `subprocess.run(args_list, shell=False)`。`command_template` 改为返回参数列表而非字符串。这是 Bridge API 变更，需要 ADR。但 V0.1.1 已冻结 Bridge——可以用"安全修复"作为例外。

### 3.4 🟡 Result.metadata 是无类型 dict

Result.metadata 是 `dict[str, Any]`。当前塞了 `duration_ms`、`capabilities`、`task_id`、`bridge`、`quota_remaining`。

**问题**:
- 没有类型约束，每个 Provider 可能塞不同的 key
- 消费者（CLI、日志、监控系统）不知道有哪些 key 可用
- 容易出现拼写错误

**技术债触发点**: 当有外部系统依赖 Result.metadata 做监控/告警时，key 不统一会导致问题。

**建议**: 定义 `ResultMetadata` 的 TypedDict 或 dataclass（但不改 Result 的 Stable 接口，只是约定）。V0.2 的 `fallback_reason` 是第一个需要规范化的 key。

### 3.5 🟡 测试覆盖不足

当前 18 个测试覆盖的是"骨架正确性"，不是"业务正确性"。

**缺失的测试**:
- Provider 降级链测试（Provider A 失败 → fallback 到 Provider B）
- 超时测试（CLI 超时后行为）
- 并发测试（多个 Task 同时执行）
- 额度耗尽测试（V0.2 需要）
- 错误传播测试（Bridge 错误 → Result.error 的完整传递）

**建议**: V0.2 随 QuotaManager 一起补充降级链测试和额度耗尽测试。

### 3.6 🟢 Git 历史管理

当前所有 commit 直接在 master 上。没有 feature branch、没有 PR review、没有 CI。

**问题**: 项目还小，可以接受。但当外部贡献者加入时，需要分支策略。

**建议**: V0.3 之前设置 GitHub Actions CI（跑测试 + zero-modification 检查）。V0.4 开始用 PR + review。

---

## 4. 哪些接口必须永远保持 Stable？

### 4.1 永远 Stable（破坏即 major version bump）

| 接口 | 理由 |
|------|------|
| `Task` dataclass | 用户输入的统一格式。改 Task = 所有 Provider 改 |
| `Result` dataclass | 输出的统一格式。改 Result = 所有消费者改 |
| `Provider.metadata` 字段 | Provider 声明格式。改字段 = 所有 Provider 改 |
| `Provider.select_bridge(task)` | 路由入口。改签名 = Router 改 |
| `Provider.supports(cap)` | 能力查询。改签名 = Registry 改 |
| `Bridge.run(task)` | 执行入口。改签名 = 所有 Bridge 改 |
| `Bridge.check_available()` | 健康检查。改签名 = 所有 Bridge 改 |
| `CapabilityRegistry.find_by_capability(cap)` | 查询接口。改签名 = Router 改 |
| `Router.route(task)` | 路由接口。改签名 = CLI 改 |
| `Router.execute(task)` | 执行接口。改签名 = CLI 改 |

### 4.2 可以扩展但不能破坏（向后兼容）

| 接口 | 扩展方式 |
|------|---------|
| `ProviderMetadata` | 只能新增字段（带默认值），不能删字段、不能改类型 |
| `Result.metadata` | 只能新增 key，不能删 key、不能改 value 类型 |
| `Task.context` | 只能新增 key |
| `CAPABILITIES` dict | 只能新增标签，不能删 |
| `KEYWORD_TO_CAPABILITY` dict | 只能新增映射，不能删 |

### 4.3 明确 Experimental（可变）

| 接口 | 何时变 Stable |
|------|-------------|
| `GUIBridge` | V0.3 实现后 |
| `BrowserBridge` | V0.5 实现后 |
| `QuotaManager`（V0.2 新增） | V0.3 使用后 |
| `BridgeResult.raw` | 可能永远是 Any |

---

## 5. 十条长期维护建议

### 1. 保持小团队决策效率

ai-hub 目前的决策模式是"用户 + AI 讨论 → 决定"。这在项目早期非常高效。当外部贡献者加入时，需要明确的决策机制。

**建议**: 建立 ADR 流程——任何架构变更必须写 ADR，ADR 由 maintainer review 后合并。不需要投票，但需要记录决策理由。

### 2. 不要变成 LLM 框架

ai-hub 的定位是"执行运行时"，不是"LLM 框架"。不要加 prompt 管理、chain-of-thought、RAG、向量数据库。

**红线**: 如果有人提议在 ai-hub 中加 prompt 模板管理 → 拒绝。Prompt 管理是 Provider/Runtime 的职责。

### 3. 保持 Bridge 基类最小

`Bridge` 基类只有 2 个抽象方法（`run` + `check_available`）。不要加 `stream()`、`cancel()`、`health()` 到基类。

**理由**: 每加一个抽象方法，所有 Bridge 子类都要实现。FakeBridge 不需要 `cancel()`，APIBridge 不需要 GUI 操作。

**建议**: 如果需要扩展功能，用 Mixin 或可选方法（`getattr(bridge, 'stream', None)`）。

### 4. 限制 core/ 文件数量

当前 `core/` 有 7 个文件：`provider.py`、`bridge.py`、`registry.py`、`result.py`、`task.py`、`capabilities.py`、`__init__.py`。

**建议**: `core/` 文件数量控制在 10 个以内。每个新文件需要 ADR 说明为什么不能放在现有文件中。V0.2 的 `quota.py` 是合理的——它是一个独立的横切关注点。

### 5. 不要加配置文件

ai-hub 当前没有 yaml/toml/json 配置文件。所有配置通过环境变量和代码常量。

**理由**: 配置文件引入解析、验证、默认值管理、文档维护的成本。在 Provider 数量 < 20 时，Python 代码就是最好的配置。

**红线**: 如果有人提议加 `ai-hub.yaml` → 拒绝。除非 Provider 数量超过 20 且用户需要动态配置。

### 6. 每个 Provider 必须有 ADR

当前 4 个 ADR 覆盖了 4 个真实 Provider。这个传统必须保持。

**理由**: ADR 记录了"这个 Provider 暴露了什么问题、为什么这么解决"。这是未来维护者理解设计意图的唯一途径。

**建议**: Contract Test 中加一项检查——如果 `providers/<name>/` 目录存在但没有对应的 `docs/adr/00NN-<name>.md`，测试失败。

### 7. README 不超过 200 行

当前 README 约 150 行，包含 Badge、Quick Start、Architecture、Compatibility Promise、Bridge Types、Terminology、Roadmap。

**问题**: README 太长会让人不想读。

**建议**: 超过 200 行时，把详细内容移到 `docs/` 下，README 只保留 Quick Start + 链接。

### 8. 版本号要有语义

当前版本是 V0.0.6 → V0.1 → V0.1.1 → V0.1.2。

**问题**: V0.0.6 和 V0.1 的区别不清晰——是 minor 还是 major？

**建议**: V1.0 之前用 `0.minor.patch` 格式。V0.1.2 = 0.1.2。V1.0 之后用 SemVer（`MAJOR.MINOR.PATCH`）。在 README 中明确版本号含义。

### 9. 建立贡献者门槛

Good First Issue 是好的开始。但需要一个 CONTRIBUTING.md 明确：
- Provider 接入必须通过 Contract Test
- 必须写 ADR
- 不允许修改 core/（除非 ADR 批准）
- Bridge.py 冻结后不允许改（除非安全修复）

**建议**: 把 CONTRIBUTING.md 写出来（当前只有标题）。这是外部贡献者看到的第一个文件。

### 10. 准备好"第一个外部贡献者"

当第一个外部 PR 到来时，maintainer 需要能快速判断：
- 这个 Provider 改了 core/ 吗？→ `git diff core/`
- Contract Test 通过吗？→ `python tests/test_provider_contract.py`
- ADR 写了吗？→ 检查 `docs/adr/`

**建议**: 把上述检查做成 GitHub Actions CI。这样 PR 自动会跑检查，maintainer 不需要手动验证。

---

## 6. 总体评价

### 做得好的

| 方面 | 评价 |
|------|------|
| 接口冻结 | 在 V0.0.6 就冻结，比大多数开源项目早 |
| 零修改承诺 | 可量化、可验证（`git diff core/`） |
| ADR 流程 | 从 V0.1 开始记录设计决策 |
| Contract Test | 强制每个 Provider 通过 |
| Bridge 分阶段 | 复杂度递增，不一次做太多 |
| 文档 | GLOSSARY + ROADMAP + ADR + Provider SDK Guide |

### 需要改进的

| 方面 | 优先级 | 建议 |
|------|--------|------|
| CI/CD | P0 | GitHub Actions: 测试 + zero-modification 检查 |
| CONTRIBUTING.md | P1 | 写清楚贡献流程 |
| 命令注入修复 | P1 | `shell=True` → `shell=False` |
| 测试覆盖 | P1 | 降级链、超时、错误传播 |
| V0.3 路线拆分 | P2 | GUIBridge 和 AI 路由分开 |
| 异步执行规划 | P2 | V0.4 考虑 `execute_async()` |

### 项目成熟度

```
V0.0 ─── V0.1 ─── V0.2 ──→ V0.3 ──→ V0.5 ──→ V1.0 ──→ V2.0
  │        │        │        │        │        │        │
  骨架     验证     横切     GUI     分解    编排     生态
  ✅       ✅       Next     ...      ...     ...     ...
```

**当前阶段**: V0.1.2 — 架构验证完成，进入功能扩展期。方向正确，节奏合理。最大的风险不是技术，而是过度设计。保持 YAGNI，保持小接口，保持零修改承诺。
