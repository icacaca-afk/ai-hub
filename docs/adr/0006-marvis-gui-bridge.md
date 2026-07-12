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

## 技术要点

### MarvisBridge 实现
- **窗口查找**: uiautomation.WindowControl（精确匹配 → 模糊匹配）
- **输入框**: 遍历 EditControl，选最大者
- **发送按钮**: 遍历 ButtonControl，匹配发送/提交关键词
- **输出提取**: 轮询 TextControl 文本变化，连续 N 次不变 = 完成
- **文本输入**: ValuePattern.SetValue（优先）→ SendKeys（降级）
- **输出提取策略**: 记录发送前文本，完成后 diff 取新增部分

### 局限
- 窗口名称硬编码 "Marvis"（若 Marvis 改名需更新）
- 依赖 Windows UIA，不可移植到 macOS/Linux
- 轮询机制不如事件驱动高效（但实现简单）
