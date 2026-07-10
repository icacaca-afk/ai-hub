# AI Hub — Architecture

> 版本：v0.0.6（冻结）
> 术语定义见 [GLOSSARY.md](GLOSSARY.md)

## 架构总览

```
┌────────────┐
│    User     │
└──────┬─────┘
       ▼
┌────────────┐
│    CLI     │  ask / history / status / caps / quota
└──────┬─────┘
       ▼
┌────────────┐
│   Router   │  Task → 关键词 → Capability
└──────┬─────┘
       ▼
┌────────────────────┐
│ CapabilityRegistry │  Capability → Provider（按优先级排序）
└──────┬─────────────┘
       ▼
┌────────────┐
│  Provider  │  metadata（声明能力）+ select_bridge(task) → Bridge
└──────┬─────┘  【不实现 execute()】
       ▼
┌────────────┐
│   Bridge   │  通信层（CLIBridge / APIBridge / FakeBridge / GUIBridge / BrowserBridge）
└──────┬─────┘  对 Provider 屏蔽 Runtime 细节
       ▼
┌────────────┐
│  Runtime   │  CLI 进程 / HTTP API / GUI / 浏览器
└────────────┘
       ↓
   Result（provider, status, output, error, artifacts, metadata）
```

## 核心数据流

```
User Input
  → Task（content + capabilities + context + artifacts）
  → Router（关键词匹配 → Capability 列表）
  → CapabilityRegistry（按 Capability 查找可用 Provider）
  → Provider.select_bridge(task) → Bridge
  → Bridge.run(task) → BridgeResult
  → Router 转换为 Result（provider, status, output, artifacts, metadata）
  → HistoryStore 记录
  → CLI 输出
```

## 关键设计原则

1. **Provider 不负责执行**——只声明能力和选择 Bridge，执行由 Router 调 Bridge.run() 完成
2. **新增 Provider 不允许修改 Router**——这是工程约束
3. **Capability 驱动路由**——Router 不知道具体 Provider 的存在，只知道 Capability
4. **Bridge 封装通信方式**——Provider 不关心底层是 CLI / API / GUI / 浏览器
5. **output 永远纯文本**——产物文件走 artifacts

## 分层职责

| 层 | 职责 | 不做什么 |
|----|------|---------|
| CLI | 解析命令、格式化输出 | 不做路由、不做执行 |
| Router | 关键词匹配、选择 Provider、调 Bridge、转 Result | 不做通信 |
| CapabilityRegistry | 注册和查找 Provider | 不做路由决策 |
| Provider | 声明能力、选择 Bridge、状态检查 | 不做执行、不做通信 |
| Bridge | 与 Runtime 通信、返回 BridgeResult | 不做路由、不做能力判断 |
| Runtime | 真正执行任务 | （外部实体） |

## 技术选型

| 选择 | 方案 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | 生态丰富、类型标注完善 |
| 数据类 | dataclass | 零依赖、足够用 |
| 序列化 | JSON / JSONL | 标准库、可读 |
| 路由 | 规则路由（关键词匹配） | V0.1 零成本；V0.3 升级 AI 路由 |
| 历史 | JSONL 文件 | V0.5 换 SQLite |
| 依赖 | 零外部依赖 | 降低安装门槛 |
