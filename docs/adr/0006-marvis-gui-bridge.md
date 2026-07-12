# ADR-0006: Marvis GUI Bridge — 不改 core/bridge.py 扩展 Bridge

## 日期
2026-07-12

## 状态
Accepted

## 背景
V0.4 目标：接入 Marvis 桌面 AI（GUI 交互），验证 "core/bridge.py 不修改也能支持全新 Bridge 类型"。

Marvis 只有桌面 GUI 界面，没有 CLI 和公开 API。无法复用 CLIBridge 或 APIBridge。

### 架构原则
**GUI Runtime 是一种 Runtime，不是 Provider。**

Provider 的职责：声明能力 + 选择 Bridge。
Bridge 的职责：封装 Runtime 通信方式。

Marvis = GUI 应用 = 一种 Runtime。MarvisBridge 封装了和这个 Runtime 的通信细节（窗口查找、控件定位、输入/输出）。Provider 只选择用哪个 Bridge，不关心底层是 CLI / API / GUI / Browser。

这个原则会被 BrowserBridge 完全复用。任何新的 Runtime 类型都应当作为 Bridge 扩展，而非 Provider 扩展。

## 决策

### 1. 不修改 core/bridge.py
core/bridge.py 已包含 GUIBridge（pyautogui）作为预留参考实现，但 Marvis 需要 Windows UIA 级别的窗口感知（pyautogui 只有坐标操作）。

新建 `providers/marvis/bridge.py`，继承 Bridge 基类，使用 uiautomation 库实现窗口查找、控件定位、文本输入/提取。

### 2. Bridge 继承方案
```python
# core/bridge.py — 不改
class Bridge(ABC):
    def run(self, task, **kwargs) -> BridgeResult: ...
    def check_available(self) -> bool: ...

# providers/marvis/bridge.py — 新增
class MarvisBridge(Bridge):
    def run(self, task, **kwargs) -> BridgeResult: ...
    def check_available(self) -> bool: ...
    def check_auth(self) -> bool: ...
```

### 3. 为什么不是修改 GuardBridge
core/bridge.py 的 GUIBridge（pyautogui）保留作为简单 GUI 操作的参考——坐标点击、截图等场景仍有用。MarvisBridge 是更高层级的封装（窗口感知 + 文本交互），职责不同，独立文件更清晰。

## 影响

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| core/bridge.py | **不改** | Bridge 基类不变 |
| core/provider.py | **不改** | Provider 基类不变 |
| core/registry.py | **不改** | CapabilityRegistry 不变 |
| router/router.py | **不改** | Router 不变 |
| providers/marvis/bridge.py | NEW | MarvisBridge (UIA) |
| providers/marvis/provider.py | NEW | MarvisProvider |
| cli/main.py | EDIT | 注册 MarvisProvider |
| tests/test_provider_contract.py | EDIT | 加 Marvis Contract Test |

## 验证

- Contract Tests: MarvisProvider 通过全部 7 项检查
- 零修改 KPI: core/ + router/ + bridge.py = 0 文件变更
- 总测试: 56/57 通过（1 个旧 test_runtime.py import 错误与此无关）

## 技术演进

### 第一版：UIA 控件树（已废弃）
- 假设 Marvis 暴露 UIA 内部控件树
- `_find_input_control` / `_find_send_button` / `_find_output_area` 遍历查找 EditControl / ButtonControl / TextControl
- **失败** — E2E 验证时发现 Marvis 是 Qt 应用（`Qt5152QWindowIcon`），Qt 默认不向 UIA 暴露内部控件树

### 第二版：Win32 键盘模拟 + 剪贴板（当前版本）
**关键洞察**：Qt / Electron / 原生 Win32 桌面应用都接受标准键盘输入和剪贴板操作。

策略：
- **输入**：剪贴板写入文字 → Ctrl+V 粘贴
- **发送**：Enter 键
- **读取输出**：Ctrl+A 全选 → Ctrl+C 复制 → 读剪贴板
- **完成检测**：轮询剪贴板内容变化，连续 N 次不变 = 响应完成
- **输出提取**：去除发送消息前缀，取增量部分

优势：
- 不依赖 UIA 控件树，Qt/Electron/原生 Win32 全通吃
- 不依赖坐标（pyautogui），窗口位置无关
- 核心模块仅 `ctypes` + `win32api`，无第三方依赖

### 局限性
- 依赖 Win32 API，不可移植到 macOS/Linux
- 操作时窗口必须在前台（会抢占焦点）
- 提取输出依赖剪贴板轮询，不如事件驱动高效
- 窗口标题硬编码 "Marvis"（若改名需更新）
