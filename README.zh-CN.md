# AI Hub

> 一个任务，任意 AI，任意运行时。

[English](README.md) | [简体中文](README.zh-CN.md)

AI Hub 是一个本地优先的 AI Runtime：它按能力路由任务，选择可用的
Provider，通过 Bridge 调用外部运行时，并返回统一结果。它统一的是 CLI、HTTP
API、浏览器和测试 Provider 的执行方式，而不是强行抹平不同模型的差异。

```text
Task → Capability → Provider → Bridge → Runtime → Result
```

## 项目状态

- 仓库最新版本：**V1.0.11**（tag `v1.0.11`）
- 当前里程碑：Pipeline Introspection，见
  [ADR-0032](docs/adr/0032-pipeline-introspection.md)
- V1.0.12 Predicate API 已在本地实现，等待发布审核，见
  [ADR-0033](docs/adr/0033-predicate-api.md)
- V1.0.11 发布时验证基线：**602 项测试通过**
- 冻结边界：`core/`、`router/router.py`、`router/health_router.py`、
  `router/score_router.py` 和现有 Provider 实现，除 Bug Fix 外不修改

目前 `pyproject.toml` 中的包版本仍是 `0.0.1`。在它与仓库标签统一前，以 Git
tag 和 ADR 里程碑作为发布版本的事实来源。

## 主要能力

- 基于 Capability 的 Provider 路由，综合健康、优先级、延迟和额度信号
- CLI、API、浏览器、MCP 与测试 Runtime 共用的 Provider/Bridge 边界
- 规则式与 LLM 辅助的多步任务规划
- 支持 Retry、Checkpoint、Condition 和 Hook 的 Execution Pipeline
- ExecutionEvent、内存 Trace、SQLite 历史记录与统计投影
- 元数据注册表和确定性序列化
- 通过 `ExecutionPipeline.describe()`、`to_dict()`、`to_json()` 无副作用查看
  Pipeline 结构

## 快速开始

需要 Python 3.11 或更高版本。具体 Provider 可能还需要安装对应 CLI、配置 API
Key 或完成登录。

```bash
git clone https://github.com/icacaca-afk/ai-hub.git
cd ai-hub
python -m pip install -e .

ai-hub status
ai-hub caps
ai-hub ask "写一个 Python HTTP 服务"
ai-hub plan "分析一个 CSV 文件并总结结论"
```

运行不依赖在线 Provider 的测试基线：

```bash
python -m pytest tests/ -x -q \
  --deselect "tests/test_benchmark.py" \
  --deselect "tests/test_cli_plan_json.py"
```

部分测试会调用已安装的外部 Runtime；需要完全隔离时，请结合仓库 pytest marker
和测试文档筛选。

## 主要命令

| 命令 | 用途 |
|---|---|
| `ai-hub ask "<任务>"` | 路由并执行单步任务 |
| `ai-hub plan "<任务>"` | 拆解并执行多步任务 |
| `ai-hub explain-route "<任务>"` | 解释 Provider 选择结果 |
| `ai-hub status` / `doctor` | 查看和诊断 Provider |
| `ai-hub benchmark` | 测量健康 Provider 的延迟和成功率 |
| `ai-hub inspect` / `trace` | 查看 Plan 和执行时间线 |
| `ai-hub exec-history` / `stats` | 查询持久化执行历史 |
| `ai-hub quota` / `caps` | 查看额度和 Capability |
| `ai-hub session` | 管理 Runtime Session |

## 架构

```text
CLI / MCP Client
        │
        ▼
Task ──► Planner / Router
        │
        ▼
ExecutionPipeline
  pre-stages → Provider Bridge → post-stages
        │
        ├──► ExecutionEvent → Trace / SQLite / Statistics
        └──► Result
```

核心架构约束：Provider 声明能力并选择 Bridge；Bridge 负责与外部 Runtime 通信。
Workflow 关注点进入 `planner/` 和 Execution Pipeline，而不是冻结的 Router 或
Provider 契约。

组件边界、运行时数据流和文档地图见[架构总览](docs/ARCHITECTURE.zh-CN.md)。

## 新增 Provider

新 Provider 放在 `providers/<name>/`，实现既有 Provider 契约：声明
`ProviderMetadata`、选择 Bridge，并提供健康、认证和额度状态。不得为了识别某个
Provider 而修改基础 Router。

提交前请阅读 [Provider 规范](docs/PROVIDER_SPEC.zh-CN.md)和
[贡献指南](CONTRIBUTING.zh-CN.md)。现有 Provider 实现属于冻结边界；真正的新
Provider 可以在自己的目录中新增。

## 文档

持续维护、面向读者的说明文档提供英文和简体中文两个版本。无语言后缀的文件是
英文，`.zh-CN.md` 是中文。ADR、外部审核、历史交接和特定版本产物是不可变档案，
保留其原始语言，不做机械翻译。

- [Documentation index](docs/README.md) · [中文文档索引](docs/README.zh-CN.md)
- [Roadmap](docs/ROADMAP.md) · [路线图](docs/ROADMAP.zh-CN.md)
- [Product](docs/PRODUCT.md) · [产品说明](docs/PRODUCT.zh-CN.md)
- [Glossary](docs/GLOSSARY.md) · [术语表](docs/GLOSSARY.zh-CN.md)
- [Provider Specification](docs/PROVIDER_SPEC.md) ·
  [Provider 规范](docs/PROVIDER_SPEC.zh-CN.md)
- [Contributing](CONTRIBUTING.md) · [贡献指南](CONTRIBUTING.zh-CN.md)

## 许可证

[MIT](LICENSE)
