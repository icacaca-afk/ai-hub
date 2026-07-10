# ARCHITECTURE.md
## AI Hub — 系统架构设计

> 版本：v0.1 架构设计
> 日期：2026-07-10
> 状态：规划中

---

## 设计原则

1. **简单优先**：能 if-else 解决的不用 AI，能配置解决的不写代码
2. **接口稳定**：Provider 接口是项目最核心的资产，第一版定义好，长期不变
3. **渐进演进**：每一层都可以独立升级，不需要推翻重来
4. **配置驱动**：能力描述、路由规则、额度信息全部外置为配置文件

---

## 系统总览

```
┌──────────────────────────────────┐
│           用户入口                │
│  (CLI / Web Chat / API)          │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│           Router                  │
│  ┌─────────┐  ┌───────────────┐  │
│  │任务分类  │→│ Provider 选择  │  │
│  └─────────┘  └───────┬───────┘  │
│                       │          │
│  ┌────────────────────┘          │
│  │                               │
│  │  ┌─────────────────────────┐  │
│  │  │ Fallback 链              │  │
│  │  │ (首选不可用 → 依次降级)   │  │
│  │  └─────────────────────────┘  │
│  └───────────────────────────────│
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│       Provider Registry           │
│  ┌────────────────────────────┐  │
│  │ providers/qoder.yaml       │  │
│  │ providers/gemini.yaml      │  │
│  │ providers/qclaw.yaml       │  │
│  │ providers/chatgpt.yaml     │  │
│  │ providers/coze.yaml        │  │
│  └────────────────────────────┘  │
│  ┌────────────────────────────┐  │
│  │ Quota Manager               │  │
│  │ (各平台额度跟踪)             │  │
│  └────────────────────────────┘  │
└──────────────┬───────────────────┘
               │
       ┌───────┼───────┬───────┐
       ▼       ▼       ▼       ▼
┌─────────┐┌────────┐┌───────┐┌──────────┐
│ QODER   ││ Gemini ││ QClaw ││ ChatGPT  │
│ Provider││Provider││Provider││ Provider │
└────┬────┘└───┬────┘└───┬───┘└────┬─────┘
     │         │         │          │
     ▼         ▼         ▼          ▼
┌──────────────────────────────────┐
│         Result Store              │
│  (任务记录 / Provider / 结果)     │
└──────────────────────────────────┘
```

---

## 五层架构

### 第一层：用户入口（Entry）

用户与系统交互的界面。

```
支持形态：
├── CLI（第一版优先，开发者最熟悉）
├── Web Chat（第二版，降低使用门槛）
└── API（第三版，供其他系统调用）
```

**第一版只做 CLI**：

```bash
$ ai-hub "写一个 Python HTTP 服务"
→ [Router] 识别为 coding 任务
→ [Provider] 选择 QODER（额度充足，优先级最高）
→ [Executor] 调用 QODER 执行
→ [Result] 返回代码

$ ai-hub "总结这个 PDF"
→ [Router] 识别为 analysis 任务
→ [Provider] 选择 QClaw
→ [Executor] 调用 QClaw 执行
→ [Result] 返回摘要
```

### 第二层：Router（路由层）

**第一版用规则路由**，不用 AI。

```
路由决策流程：

1. 任务分类
   - 通过关键词匹配判断任务类型
   - 类型映射：coding / analysis / search / file_ops / general

2. 候选筛选
   - 从 Provider Registry 中找出支持该任务类型的 Provider
   - 过滤掉：未登录的、额度用尽的、状态异常的

3. 优先级排序
   - 按 YAML 配置中的 priority 字段排序
   - 同优先级下，选额度最多的

4. Fallback
   - 首选不可用时，按 fallback 链依次尝试
   - 全部不可用时，告知用户
```

**路由规则配置示例**（`router_rules.yaml`）：

```yaml
rules:
  - task_type: coding
    providers:
      - qoder        # priority: 100
      - gemini_cli   # priority: 80
      - chatgpt      # priority: 60

  - task_type: analysis
    providers:
      - qclaw        # priority: 100
      - gemini_cli   # priority: 80
      - chatgpt      # priority: 60

  - task_type: search
    providers:
      - gemini_cli   # priority: 100
      - qclaw        # priority: 80

  - task_type: file_ops
    providers:
      - qclaw        # priority: 100

  - task_type: general
    providers:
      - gemini_cli   # priority: 100
      - chatgpt      # priority: 80
      - qclaw        # priority: 60
```

**关键词映射示例**（`task_keywords.yaml`）：

```yaml
coding:
  - 写代码
  - 写一个
  - 实现
  - 开发
  - 重构
  - 调试
  - bug
  - 函数
  - 类
  - API
  - deploy
  - 部署

analysis:
  - 总结
  - 分析
  - 摘要
  - 提取
  - 读
  - 看看
  - review

search:
  - 搜索
  - 查
  - 找
  - 搜一下
  - 查一下
  - 最新

file_ops:
  - 整理
  - 移动
  - 重命名
  - 压缩
  - 清理

general:
  - 翻译
  - 写邮件
  - 起名字
  - 建议
```

### 第三层：Provider Registry（注册中心）

维护所有已接入 Provider 的元信息。

**目录结构**：

```
ai-hub/
├── providers/
│   ├── qoder.yaml
│   ├── gemini_cli.yaml
│   ├── qclaw.yaml
│   ├── chatgpt.yaml
│   └── coze.yaml
├── config/
│   ├── router_rules.yaml
│   └── task_keywords.yaml
├── quota/
│   └── quota_state.json    # 运行时更新
└── history/
    └── tasks.jsonl          # 运行时追加
```

**Provider 配置文件格式**（`providers/qoder.yaml`）：

```yaml
# Provider 基础信息
provider: qoder
display_name: QODER
description: 阿里 Agentic 编程平台

# 能力描述
capabilities:
  - coding
  - debug
  - refactor

# 任务类型支持
task_types:
  - coding

# 路由优先级（同任务类型下，数字越大越优先）
priority: 100

# 额度信息
quota:
  type: daily
  total: 80
  remaining: 80    # 运行时更新
  reset_at: null   # 运行时更新
  auto_detect: false  # 第一版手动维护

# 健康检查
health_check:
  method: cli
  command: "qoder --version"
  expect: "qoder"

# 登录检查
auth_check:
  method: cli
  command: "qoder auth status"
  expect_contains: "logged in"

# 调用方式
executor:
  type: cli
  command_template: "qoder run \"{task}\""
  timeout: 300

# Fallback 链
fallback:
  - gemini_cli
  - chatgpt

# 状态
status: enabled
```

### 第四层：Providers（执行层）

每个 Provider 是一个独立的执行单元，实现统一接口。

**统一接口**（伪代码，具体语言待定）：

```
Provider 接口：
  available()    → bool      检查是否可用（登录 + 额度 + 健康）
  execute(task)  → Result    执行任务
  quota_left()   → int       返回剩余额度
  health()       → Status    返回健康状态
```

**Result 统一格式**：

```json
{
  "task_id": "20260710-001",
  "provider": "qoder",
  "status": "success",
  "output": "生成的代码或文本内容",
  "metadata": {
    "duration_ms": 3200,
    "tokens_used": 500,
    "quota_remaining": 79
  },
  "raw": null
}
```

### 第五层：Result Store（结果存储）

记录所有任务执行历史。

**存储格式**（JSONL，每行一个任务）：

```json
{"task_id":"20260710-001","timestamp":"2026-07-10T22:00:00+08:00","input":"写一个 Python HTTP 服务","task_type":"coding","provider":"qoder","status":"success","duration_ms":3200,"output":"from http.server import ...","quota_remaining":79}
```

**查询功能**（第一版只支持基础查询）：

```bash
$ ai-hub history                    # 最近 10 条
$ ai-hub history --provider qoder   # 按 Provider 过滤
$ ai-hub history --type coding      # 按任务类型过滤
```

---

## 演进预留

### V0.1 → V0.3 升级路径

```
V0.1（规则路由）
  ↓ Router 从 if-else 升级为 AI 判断
V0.3（智能路由）
  ↓ 增加 Task Splitter 模块
V0.5（任务分解）
  ↓ 增加 Planner + Orchestrator
V1.0（Agent 编排）
  ↓ 增加 Plugin 系统
V2.0（插件生态）
```

**关键**：每一层升级都不推翻前一层。

| 升级步骤 | 改什么 | 不改什么 |
|---------|--------|---------|
| V0.1 → V0.3 | Router 内部从规则改为 AI 调用 | Provider 接口、配置格式、Result 格式 |
| V0.3 → V0.5 | Router 前增加 Splitter | Router、Provider、Result 不变 |
| V0.5 → V1.0 | Splitter 升级为 Planner + Orchestrator | Provider 接口不变（Agent 是 Provider 的超集） |
| V1.0 → V2.0 | 增加 Plugin Loader | 现有 Provider 自动成为内置插件 |

### 预留接口

为未来升级预留的两个接口（第一版不用，但定义好）：

```
supports(task_type) → bool
  判断 Provider 是否支持某任务类型
  V0.3 的 AI Router 可直接调用

cost() → { currency, amount }
  返回单次调用成本
  V0.5+ 的成本优化路由可调用
```

---

## 技术选型建议

| 组件 | 第一版选择 | 理由 | 后续可替换 |
|------|-----------|------|-----------|
| 开发语言 | Python | AI 生态最丰富，CLI 开发快 | 可用 Go 重写性能关键路径 |
| CLI 框架 | Click / Typer | Python CLI 标准选择 | - |
| 配置格式 | YAML | 人可读写，开发者熟悉 | - |
| 存储 | JSONL 文件 | 无需数据库，简单可靠 | V0.5+ 换 SQLite |
| 路由 | 规则引擎（if-else + 配置） | 简单可控，无需 AI | V0.3 换 LLM 路由 |
| 进程管理 | subprocess | 调用各平台 CLI | - |

---

## 不画的东西

这份架构图里**故意没有**画的东西：

| 没画的 | 原因 |
|--------|------|
| Planner / Orchestrator | V1.0 才有 |
| Memory / Context Store | V1.0 才有 |
| Vector DB | V2.0 才有 |
| Event Bus / Message Queue | V1.0 才有 |
| Plugin Loader | V2.0 才有 |
| Web UI | V0.2 才有 |
| Auth / 权限系统 | 不在规划内（个人工具） |
| 飞书 / Lark CLI | V1.0 才有 |
| Prompt 模板系统 | V0.5 才有 |
