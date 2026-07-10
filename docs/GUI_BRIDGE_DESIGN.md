# GUI Bridge Design

> **版本**: Design Document（不含代码）
> **日期**: 2026-07-11
> **状态**: Draft
> **前置条件**: CLIBridge Stable (V0.1.1), APIBridge Stable (V0.1.2)
> **目标版本**: V0.3

---

## 1. 为什么需要 GUI Bridge

### 1.1 现状

| Bridge | 通信方式 | 适用平台 | 状态 |
|--------|---------|---------|------|
| FakeBridge | 不通信 | 测试 | ✅ Stable |
| CLIBridge | subprocess | Gemini CLI, QODER | ✅ Stable |
| APIBridge | HTTP | DeepSeek, OpenAI | ✅ Stable |
| **GUIBridge** | **GUI 自动化** | **Marvis, 桌面 AI 应用** | **⏳ V0.3** |
| BrowserBridge | 浏览器控制 | ChatGPT Web, Claude Web | ⏳ V0.5 |

有些 AI 工具只提供 GUI 接口——没有 CLI、没有公开 API。Marvis 是典型例子：一个桌面 AI 助手，只能通过图形界面交互。

### 1.2 GUI Bridge 的核心挑战

与 CLI/API 的本质区别：

| 维度 | CLI / API | GUI |
|------|-----------|-----|
| 通信模型 | 请求 → 响应 | 操作 → 状态轮询 |
| 状态管理 | 无状态（每次新进程/新请求） | 有状态（应用持续运行） |
| 输出获取 | stdout / HTTP body | 屏幕读取 / OCR / UI 树解析 |
| 错误检测 | exit code / HTTP status | UI 元素状态 / 异常弹窗 |
| 超时处理 | kill process / abort request | 关闭对话框 / 发送取消 |
| 并发 | 天然隔离（独立进程/请求） | 共享一个 GUI 实例，需要序列化 |

---

## 2. GUI Bridge 的职责边界

### 2.1 GUI Bridge 做什么

1. **启动/连接 GUI 应用**：找到正在运行的 Marvis 窗口，或启动新实例
2. **输入提交**：将 Task.content 输入到 GUI 的输入框
3. **输出提取**：从 GUI 中提取 AI 的回复文本
4. **状态检测**：判断任务是否完成（停止生成动画、出现特定 UI 元素）
5. **异常处理**：弹窗关闭、应用崩溃、超时

### 2.2 GUI Bridge 不做什么

| 不做的事 | 原因 | 谁来做 |
|---------|------|--------|
| GUI 应用内部的会话管理 | 这是 Runtime 的职责 | Marvis 自己 |
| 多轮对话上下文维护 | Task 已携带 context | Router / Provider |
| GUI 截图保存 | 不是 Bridge 的核心职责 | 可作为 artifacts 可选输出 |
| GUI 应用安装/配置 | 运维问题 | 用户 |
| 跨平台 GUI 框架抽象 | V0.3 只需支持 Windows | GUIBridge 实现 |

### 2.3 与 Provider 的关系

**Provider 不感知 GUI。**

Provider 只声明"我用 GUIBridge"，不关心 GUI 怎么操作。这和 CLIBridge/APIBridge 一致：

```
MarvisProvider
  ├── metadata: capabilities=["code.generate", "general.chat"], priority=30
  └── bridge: GUIBridge(app_name="Marvis")
```

Provider 的 `select_bridge(task)` 返回 GUIBridge 实例。Router 调用 `bridge.run(task)` 执行。

### 2.4 与 Runtime 的关系

**GUI Bridge 是 Runtime 的适配器，不是 Runtime 的控制器。**

- Runtime = Marvis 应用进程（独立运行）
- GUIBridge = 通过 OS 级 GUI 自动化 API 与 Marvis 通信的适配器
- GUIBridge **不拥有** Marvis 进程（不像 CLIBridge 启动子进程）

这意味着：
- GUIBridge 启动前，Marvis 应该已经在运行（或 GUIBridge 帮忙启动，但不管理生命周期）
- Marvis 崩溃后，GUIBridge 的 `check_available()` 返回 False
- GUIBridge 不负责 Marvis 的更新、配置、账号登录

---

## 3. Session 概念

### 3.1 GUI Bridge 需要 Session

CLIBridge 和 APIBridge 是无状态的：每次 `run()` 是独立的进程/请求。

GUIBridge 不同：Marvis 持续运行，多个 Task 可能在同一个 Marvis 会话中。如果不管理 Session：

- Task A 的输出和 Task B 的输出混在一起
- 无法区分"新回复"和"历史回复"
- 多个 Task 并发提交会互相干扰

### 3.2 Session 设计

```python
# 概念设计（不是最终接口）
class GUISession:
    session_id: str          # 唯一标识
    created_at: float        # 创建时间
    last_task_id: str        # 最后一个 Task
    output_marker: str       # 输出位置标记（用于区分新旧输出）
```

**Session 生命周期**:
1. GUIBridge 初始化时创建 Session（或复用已有 Session）
2. 每次 `run(task)` 前记录输出位置
3. `run(task)` 后等待新输出出现
4. 提取新输出作为 BridgeResult.output
5. Session 超时（如 30 分钟无活动）自动关闭

### 3.3 Session 不暴露给 Provider

Session 是 GUIBridge 的内部实现细节。Provider 和 Router 不知道 Session 的存在。

---

## 4. 最小接口设计

### 4.1 GUIBridge 接口

GUIBridge 必须继承 `Bridge` 基类，实现两个抽象方法：

```python
class GUIBridge(Bridge):
    def __init__(
        self,
        app_name: str,           # 目标应用名称（如 "Marvis"）
        timeout: int = 300,      # 单次任务超时
        session_reuse: bool = True,  # 是否复用 Session
    ):
        ...

    def run(self, task: Task, **kwargs) -> BridgeResult:
        """
        1. 找到 app_name 对应的窗口
        2. 记录当前输出位置（Session marker）
        3. 在输入框中输入 task.content
        4. 点击发送按钮
        5. 轮询等待输出完成（超时检测、完成信号检测）
        6. 提取新输出文本
        7. 返回 BridgeResult
        """
        ...

    def check_available(self) -> bool:
        """检查 app_name 对应的应用是否在运行。"""
        ...
```

### 4.2 不需要的接口

| 方法 | 原因 |
|------|------|
| `check_auth()` | GUI 应用的认证状态由应用自身管理。`check_available()` 包含了"应用在运行且可交互"的语义。 |
| `stream()` | V0.3 不做流式输出 |
| `cancel()` | V0.3 不做任务取消（超时直接返回 failed） |
| `new_session()` | Session 是内部实现，不暴露 |

### 4.3 BridgeResult 扩展

GUIBridge 的 `run()` 返回标准 BridgeResult，但可能利用以下字段：

| 字段 | GUI 场景的用途 |
|------|--------------|
| `output` | 从 GUI 提取的文本回复 |
| `artifacts` | 可选：截图路径（如果用户开启了截图） |
| `raw` | GUI 自动化框架的原始返回（如 UI 树快照） |
| `duration_ms` | 从输入提交到输出完成的总耗时 |

---

## 5. 技术选型方向

### 5.1 Windows 平台（V0.3 首选）

| 方案 | 优势 | 劣势 |
|------|------|------|
| `pywinauto` | 成熟，支持 Win32/UIA | 依赖 COM，调试困难 |
| `uiautomation` | 纯 Python，UIA 封装 | 社区小 |
| `pyautogui` | 简单，跨平台 | 基于坐标，脆弱 |
| `keyboard` + `pytesseract` | 极简 | OCR 不可靠 |

**建议**: `uiautomation` 作为首选。理由：
- 纯 Python，无 COM 依赖
- UIA 是 Windows 官方辅助功能 API，比坐标操作稳定
- 能直接读取 UI 树，比 OCR 可靠

### 5.2 跨平台（V0.4+）

- macOS: `pyobjc` + Accessibility API
- Linux: `python-atspi`
- **V0.3 不做跨平台**。先在 Windows 上跑通一个 Marvis Provider。

---

## 6. V0.3 不应该做什么

| 不做的事 | 原因 | 什么时候做 |
|---------|------|----------|
| 多窗口管理 | 一个 GUIBridge 对应一个应用窗口 | V0.5+ |
| GUI 录制/回放 | 复杂度高，需求不明确 | V1.0+ |
| 远程 GUI（RDP/VNC） | 网络层复杂度 | V2.0+ |
| 跨平台 | 先跑通 Windows | V0.4 |
| 流式输出 | 需要轮询 UI 变化，体验不稳定 | V0.5+ |
| 多会话并发 | GUI 天然单线程交互 | 永远不做（用序列化） |
| GUI 主题/布局适配 | 假设 Marvis 的 UI 相对稳定 | 永远不做（出问题再说） |
| 自动安装 Marvis | 运维问题，不是 Bridge 职责 | 永远不做 |

---

## 7. GUI Bridge vs Browser Bridge

| 维度 | GUIBridge | BrowserBridge |
|------|-----------|---------------|
| 目标 | 桌面应用（Marvis） | Web 应用（ChatGPT Web, Claude Web） |
| 通信 | OS 级 GUI API | CDP / Playwright |
| Session | 应用内会话 | 浏览器标签页 |
| 输入 | UI 输入框 | DOM 元素 |
| 输出 | UI 树 / OCR | DOM 提取 |
| 稳定性 | 中（UI 变更影响大） | 高（DOM 结构相对稳定） |
| 跨平台 | 需要适配 | 天然跨平台 |

**结论**: GUIBridge 和 BrowserBridge 是完全不同的 Bridge 类型，不共享实现。但它们共享 Session 概念。

---

## 8. 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Marvis UI 变更导致 Bridge 失效 | 高 | 高 | ADR 记录 UI 操作步骤；Contract Test 检查关键 UI 元素存在 |
| GUI 自动化框架不稳定 | 中 | 高 | 优先用 UIA（官方 API），避免坐标操作 |
| 输出提取不完整 | 中 | 中 | 多策略：先 UI 树，失败则截图+OCR |
| 并发任务互相干扰 | 高 | 高 | GUIBridge 内部加锁，序列化所有 run() 调用 |
| Session 管理复杂度蔓延 | 中 | 中 | V0.3 只做最简 Session（单窗口、单会话、超时关闭） |

---

## 9. 验收标准（V0.3）

| # | 验收项 |
|---|--------|
| 1 | MarvisProvider + GUIBridge 端到端调用成功 |
| 2 | `core/provider.py` 未修改 |
| 3 | `core/bridge.py` 未修改（GUIBridge 继承 Bridge，不改基类） |
| 4 | Contract Test 通过 |
| 5 | 现有 18 个测试全过 |
| 6 | ADR-0006: GUI Bridge 设计决策 |
| 7 | GUI 操作步骤文档化（哪些 UI 元素、什么操作序列） |

---

## 10. 总结

GUIBridge 是 ai-hub 中最复杂的 Bridge 类型，因为 GUI 交互本质上是有状态的、脆弱的、平台相关的。

**V0.3 的核心原则**:
1. **最小可用**：只支持 Windows + Marvis，一个 Provider 跑通就行
2. **隔离复杂度**：Session、UI 操作、输出提取全部封装在 GUIBridge 内部，不泄漏到 Provider/Router
3. **不破坏 Stable 接口**：GUIBridge 继承 Bridge 基类，不改基类
4. **YAGNI**：不做跨平台、不做多窗口、不做流式、不做并发
