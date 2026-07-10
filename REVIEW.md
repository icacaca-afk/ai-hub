# AI Hub — APIBridge 实现 Review

> 日期：2026-07-11
> 状态：Review 记录

---

## 1. 本次实现概述

### 完成的工作

1. **APIBridge 增强**（`core/bridge.py`）
   - 新增 `body_template`：请求体模板机制（对应 CLIBridge 的 `command_template`），支持 `{task}`、`{model}` 占位符
   - 新增 `response_extractor`：响应提取路径（如 `choices[0].message.content`），从 JSON 响应中提取输出文本
   - 新增 `health_endpoint`：健康检查端点（对应 CLIBridge 的 `version_command`）
   - 增强错误处理：HTTPError 时读取响应体，URLError 单独处理
   - 支持 `raw` 字段保存原始响应，方便调试

2. **OpenAI Compatible Provider**（`providers/openai_compatible/`）
   - 新增通用 OpenAI 兼容 API Provider
   - 支持任何实现 `/v1/chat/completions` 规范的服务（OpenRouter、Together AI、本地 Ollama 等）
   - 环境变量配置：`OPENAI_COMPATIBLE_API_KEY`、`OPENAI_COMPATIBLE_BASE_URL`、`OPENAI_COMPATIBLE_MODEL`

3. **OpenAI API Provider 更新**（`providers/openai_api/provider.py`）
   - 从旧的通用格式改为使用 OpenAI Chat Completions 格式
   - 配置 `body_template` 和 `response_extractor`
   - 新增 `health_endpoint` (`/v1/models`)

---

## 2. 架构问题 Review

### 问题 1：Bridge 基类缺少 `check_auth()` 方法声明

**现状**：
- `Bridge` 基类只声明了 `run()` 和 `check_available()` 两个抽象方法
- 但 `CLIBridge`、`APIBridge`、`FakeBridge` 都实现了 `check_auth()` 方法
- `Provider.available()` 中调用的是 `self.bridge.check_available()`，没有调用 `check_auth()`

**影响**：
- `check_auth()` 不是 Bridge 接口的一部分，但实际所有实现都有
- Provider 自己实现 `authenticated()` 时绕过了 Bridge，直接检查环境变量/调用 auth 命令
- 接口不统一，新增 Bridge 时容易遗漏

**建议**：
- 在 `Bridge` 基类中增加 `check_auth()` 抽象方法
- 或者统一 `available()` 的语义为「Bridge 可用 + 已认证」，Provider 层不再单独处理认证

---

### 问题 2：Provider 重复实现环境变量读取逻辑

**现状**：
- 每个 Provider 都在模块级别读取环境变量（`GEMINI_API_KEY`、`OPENAI_API_KEY`、`QODER_*` 等）
- `authenticated()` 方法里又检查一遍环境变量
- Bridge 内部也通过 `api_key_env` / `env` 读取环境变量

**影响**：
- 环境变量读取逻辑分散在三处（模块级、Provider、Bridge）
- 容易出现不一致（比如 Provider 检查了变量但 Bridge 又读了一遍）
- 测试时需要 mock 环境变量

**建议**：
- 统一由 Bridge 处理认证相关的环境变量
- Provider 的 `authenticated()` 直接调用 `self.bridge.check_auth()`
- 减少重复代码

---

### 问题 3：body_template 只支持字符串占位符，不支持更复杂的动态构建

**现状**：
- `body_template` 使用 Python `str.format()` 做简单替换
- 只能替换字符串值，不能动态添加/删除字段
- 比如无法根据 `task.context` 中的历史记录构建 messages 数组

**影响**：
- 对于需要多轮对话的场景，当前模板机制不够用
- Provider 可能需要绕过 `body_template` 自己构建请求体
- 长远来看可能需要更灵活的构建器

**建议**：
- V0.1 阶段简单模板够用，暂不改动
- V0.2 考虑增加 `body_builder` 回调函数选项，支持完全自定义请求体构建
- 保持向后兼容：有 `body_builder` 用 builder，没有就用 template

---

### 问题 4：response_extractor 路径解析用正则简单拆分，边界情况可能出错

**现状**：
- `_extract_output` 用 `re.findall(r'[^.\[\]]+', path)` 来解析路径
- 对于 `choices[0].message.content` 这种简单路径没问题
- 但如果 key 本身包含 `.` 或 `[` 字符就会出错（虽然实际 API 中很少见）

**影响**：
- 极低概率的边界问题
- 不影响当前 OpenAI 兼容格式的使用

**建议**：
- 当前实现满足需求，暂不改动
- 如果以后遇到复杂路径，考虑换用更健壮的 JSONPath 实现

---

### 问题 5：health_endpoint 的 base URL 拼接逻辑不够健壮

**现状**：
- `check_available()` 中拼接 base URL 的逻辑：
  ```python
  base = self.endpoint.rsplit("/", 2)[0] if "/v1/" in self.endpoint else self.endpoint.rsplit("/", 1)[0]
  ```
- 硬编码了 `/v1/` 路径判断
- 对于不包含 `/v1/` 的 API 可能出错

**影响**：
- 非标准路径的 API 健康检查可能失败
- 但大多数 OpenAI 兼容 API 都遵循 `/v1/` 规范

**建议**：
- V0.1 阶段可以接受
- 后续考虑让 Provider 直接传完整的 health URL，或者提供更灵活的 base_url 配置

---

### 问题 6：openai_api 与 openai_compatible 功能重叠

**现状**：
- `openai_api` 和 `openai_compatible` 本质上都是 OpenAI Chat Completions API
- 区别只是 base_url 不同，其他逻辑完全一样
- 维护两份几乎相同的代码

**影响**：
- 代码重复
- 新增功能需要改两处

**建议**：
- `openai_api` 可以作为 `openai_compatible` 的特例（默认指向 OpenAI 官方端点）
- 或者保留两个但让 `openai_api` 继承自 `openai_compatible`
- V0.1 阶段可以先保留，后续重构

---

## 3. 遵守的约束

| 约束 | 状态 | 说明 |
|------|------|------|
| 不修改 `core/provider.py` | ✅ | 未修改 |
| 不修改 `router/` | ✅ | 未修改 |
| 不修改 Task / Result | ✅ | 未修改 |
| 尽量不修改 `core/bridge.py` | ⚠️ | 已修改，原因：原 APIBridge 是骨架实现，需要增强才能支持真实 API 格式（详见下文） |

### 修改 core/bridge.py 的原因

原始 APIBridge 存在以下问题，无法满足实际使用需求：

1. **请求体格式硬编码**：固定为 `{"task": ..., "capabilities": ...}`，不是任何主流 API 的格式
2. **缺少响应解析**：直接返回原始 JSON 字符串，用户看到的是未处理的 JSON 而不是文本回复
3. **缺少健康检查机制**：CLIBridge 有 `version_command` 检查可用性，APIBridge 没有对应的 HTTP 健康检查
4. **无法适配不同 API**：不同 API 有不同的请求/响应格式，需要模板化配置

因此必须修改 `core/bridge.py` 中的 APIBridge 实现。
Bridge 基类和其他 Bridge 实现（CLIBridge、FakeBridge、GUIBridge、BrowserBridge）均未改动。

---

## 4. 测试结果

所有测试通过：

- `tests/test_skeleton.py` — ✅ 12/12 通过
- `tests/validate_provider.py` — ✅ 5/5 Provider 通过（新增 OpenAICompatibleProvider）
- APIBridge 单元测试 — ✅ 6/6 通过

---

## 5. 后续建议

1. **V0.2**：考虑 `openai_api` 与 `openai_compatible` 的合并/继承
2. **V0.2**：增加 `body_builder` 回调支持更复杂的请求体构建
3. **V0.2**：在 Bridge 基类中正式声明 `check_auth()` 方法
4. **V0.3**：支持流式输出（SSE）
5. **V0.3**：支持多轮对话（history → messages）
