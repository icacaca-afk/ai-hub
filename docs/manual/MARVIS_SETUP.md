# Marvis 接入指南

## 前置条件

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10+（依赖 Windows UI Automation） |
| Marvis | 已安装并启动，主窗口可见 |
| Python | 3.10+ |
| 依赖 | `pip install uiautomation` |

## 安装

```bash
# 在 ai-hub 目录下
pip install uiautomation
```

## 启动 Marvis

1. 启动 Marvis 桌面应用
2. 确保主窗口可见，标题包含 "Marvis"
3. 确保输入框可用（可输入文字）
4. 确保已登录（不需要额外认证配置）

## 第一次连接

```bash
# 检查 Marvis 是否可访问
ai-hub status

# 应显示：
# marvis: Available / Unavailable

# 如果 Available，直接使用
ai-hub ask "用 Python 写一个 hello world"
```

## 权限

MarvisBridge 通过 Windows UI Automation 读写 Marvis 窗口控件：
- **无管理员权限要求**
- **不修改 Marvis 配置**
- **不访问文件系统**

## 验证

```bash
# 冒烟测试
ai-hub ask "回复 hello"

# 预期输出：
# [marvis] hello (或类似问候语)
```

## 常见失败

| 症状 | 原因 | 解决 |
|------|------|------|
| `Window not found` | Marvis 未启动 | 启动 Marvis |
| `Input control not found` | Marvis 窗口布局变化 | 确认输入框可见 |
| `health: False` | Marvis 窗口不在前台 | 切换到 Marvis 窗口 |
| `uiautomation not installed` | 缺少依赖 | `pip install uiautomation` |

## 已知局限

- **仅 Windows**：uiautomation 依赖 Windows UI Automation
- **窗口名称敏感**：硬编码 "Marvis"，若应用改名需更新 `app_name` 参数
- **不支持流式输出**：等 AI 回复完成后一次性读取
- **不支持多窗口**：仅操作第一个匹配的窗口
- **轮询机制**：非事件驱动，响应有 1-5 秒延迟

## 架构

```
User → CLI (ai-hub ask)
            ↓
        Router
            ↓
    CapabilityRegistry
            ↓
    MarvisProvider (select_bridge)
            ↓
    MarvisBridge (UIA)
            ↓
    Marvis Desktop App
            ↓
    AI Response
            ↓
    BridgeResult → Result → stdout
```
