# PROVIDER_SPEC.md
## AI Hub — Provider 接口规范

> 版：v0.1
> 日期：2026-07-10
> 状态：规划中

---

## 设计理念

**Provider 接口是整个项目最核心、最稳定的资产。**

- 接口一旦定义，长期不变
- 每个 AI 平台（QODER、Gemini CLI、QClaw、ChatGPT……）都是一个 Provider
- 未来 Agent 只是 Provider 的一种特殊实现
- 新增 Provider = 新增一个配置文件 + 一个适配器，不改核心代码

---

## 核心接口

```
class Provider:
    """所有 AI 平台适配器必须实现的接口"""

    # ─── 元信息 ───

    name: str                    # 唯一标识符，如 "qoder"
    display_name: str            # 用户可见名称，如 "QODER"
    description: str             # 一句话描述
    version: str                 # Provider 适配器版本，如 "0.1.0"

    # ─── 能力描述 ───

    capabilities: list[str]      # 能力标签，如 ["coding", "debug", "refactor"]
    task_types: list[str]        # 支持的任务类型，如 ["coding"]

    # ─── 路由信息 ───

    priority: int                # 同任务类型下的优先级，越大越优先（0-100）
    fallback: list[str]          # 不可用时的降级 Provider 名称链

    # ─── 状态检查 ───

    def available(self) -> bool:
        """检查 Provider 是否可用（健康 + 登录 + 额度三者均通过）"""
        return self.health() and self.authenticated() and self.quota_left() > 0

    def health(self) -> bool:
        """检查 Provider 服务是否在线"""
        ...

    def authenticated(self) -> bool:
        """检查用户是否已登录"""
        ...

    # ─── 额度管理 ───

    def quota_left(self) -> int:
        """返回剩余免费额度（次数），无限制返回 -1"""
        ...

    def quota_info(self) -> dict:
        """返回额度详情"""
        return {
            "type": "daily" | "monthly" | "unlimited" | "unknown",
            "total": int,
            "remaining": int,
            "reset_at": "ISO-8601" | None,
            "auto_detect": bool    # 是否自动检测额度
        }

    # ─── 执行 ───

    def execute(self, task: str, context: dict = None) -> Result:
        """
        执行任务，返回统一格式的结果。

        参数：
            task:    用户的任务描述（自然语言）
            context: 可选的上下文信息（历史记录、文件路径等）

        返回：
            Result 对象
        """
        ...

    # ─── 预留接口（第一版不用，但必须定义）───

    def supports(self, task_type: str) -> bool:
        """判断是否支持某任务类型"""
        return task_type in self.task_types

    def cost(self) -> dict:
        """返回单次调用成本"""
        return {
            "currency": "CNY" | "USD" | None,
            "amount": float,      # 0 表示免费
            "unit": "per_call" | "per_token"
        }
```

---

## 统一结果格式

所有 Provider 的 `execute()` 必须返回 `Result` 对象：

```json
{
  "task_id": "20260710-001",
  "provider": "qoder",
  "status": "success | failed | timeout | partial",
  "output": "任务的输出内容（代码 / 文本 / JSON 等）",
  "error": null,
  "metadata": {
    "duration_ms": 3200,
    "tokens_used": 500,
    "quota_remaining": 79,
    "model": "qoder-default"
  },
  "raw": null
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | ✅ | 唯一任务 ID，格式 `YYYYMMDD-NNN` |
| `provider` | string | ✅ | 执行该任务的 Provider 名称 |
| `status` | enum | ✅ | `success`/`failed`/`timeout`/`partial` |
| `output` | string | ✅ | 任务输出内容；失败时为错误描述 |
| `error` | string\|null | ✅ | 错误详情；成功时为 null |
| `metadata` | object | ✅ | 执行元数据 |
| `metadata.duration_ms` | int | ✅ | 执行耗时（毫秒） |
| `metadata.tokens_used` | int | ❌ | 使用的 Token 数 |
| `metadata.quota_remaining` | int | ❌ | 执行后剩余额度 |
| `metadata.model` | string | ❌ | 使用的模型名称 |
| `raw` | object\|null | ✅ | Provider 原始返回（调试用）；正常为 null |

### status 枚举

| 状态 | 含义 | 是否消耗额度 |
|------|------|------------|
| `success` | 任务成功完成 | 是 |
| `failed` | 任务执行失败（Provider 侧错误） | 视 Provider 而定 |
| `timeout` | 执行超时 | 否（第一版不扣额度） |
| `partial` | 部分完成（如长文本被截断） | 是 |

---

## Provider 配置文件规范

每个 Provider 除了代码适配器，还需要一份 YAML 配置文件。

**文件位置**：`providers/{name}.yaml`

**完整示例**（`providers/qoder.yaml`）：

```yaml
# ═══ 基础信息 ═══
provider: qoder
display_name: QODER
description: 阿里 Agentic 编程平台
version: "0.1.0"

# ═══ 能力描述 ═══
capabilities:
  - coding
  - debug
  - refactor

task_types:
  - coding

# ═══ 路由配置 ═══
priority: 100
fallback:
  - gemini_cli
  - chatgpt

# ═══ 额度配置 ═══
quota:
  type: daily
  total: 80
  remaining: 80
  reset_at: null
  auto_detect: false

# ═══ 成本配置（预留）═══
cost:
  currency: null
  amount: 0
  unit: per_call

# ═══ 健康检查 ═══
health_check:
  method: cli
  command: "qoder --version"
  expect_contains: "qoder"
  timeout: 10

# ═══ 登录检查 ═══
auth_check:
  method: cli
  command: "qoder auth status"
  expect_contains: "logged in"
  timeout: 10

# ═══ 执行配置 ═══
executor:
  type: cli
  command_template: "qoder run \"{task}\""
  timeout: 300
  workdir: null

# ═══ 状态 ═══
status: enabled
```

---

## 第一版接入的 Provider 清单

按接入优先级排序：

| 优先级 | Provider | 任务类型 | 接入方式 | 免费额度 | 备注 |
|--------|----------|---------|---------|---------|------|
| 1 | **QODER** | coding | CLI | 每日 80 次 | 编程任务首选 |
| 2 | **Gemini CLI** | search, general | CLI | 无明确限制 | 搜索和通用任务首选 |
| 3 | **QClaw** | analysis, file_ops | OpenClaw API | 有免费额度 | 分析和文件处理 |

后续接入：

| 优先级 | Provider | 任务类型 | 接入方式 | 备注 |
|--------|----------|---------|---------|------|
| 4 | ChatGPT | general, coding | API | 需 API Key |
| 5 | Coze | workflow | API | 工作流类任务 |
| 6 | Marvis | file_ops | CLI | 系统操作 |
| 7 | Trae Work | parallel | API | 并行任务 |

---

## Provider 适配器实现模板

每个 Provider 需要实现一个适配器类。以 QODER 为例（伪代码）：

```python
class QoderProvider(Provider):
    """QODER 适配器"""

    name = "qoder"
    display_name = "QODER"
    description = "阿里 Agentic 编程平台"
    capabilities = ["coding", "debug", "refactor"]
    task_types = ["coding"]
    priority = 100
    fallback = ["gemini_cli", "chatgpt"]

    def __init__(self, config_path="providers/qoder.yaml"):
        self.config = load_yaml(config_path)
        self.quota_state = load_quota_state("quota/quota_state.json")

    def health(self) -> bool:
        result = run_command(self.config["health_check"]["command"], timeout=10)
        return self.config["health_check"]["expect_contains"] in result

    def authenticated(self) -> bool:
        result = run_command(self.config["auth_check"]["command"], timeout=10)
        return self.config["auth_check"]["expect_contains"] in result

    def quota_left(self) -> int:
        return self.quota_state.get("qoder", {}).get("remaining", 0)

    def quota_info(self) -> dict:
        return {
            "type": self.config["quota"]["type"],
            "total": self.config["quota"]["total"],
            "remaining": self.quota_left(),
            "reset_at": self.quota_state.get("qoder", {}).get("reset_at"),
            "auto_detect": self.config["quota"]["auto_detect"]
        }

    def execute(self, task: str, context: dict = None) -> Result:
        start = time.time()
        command = self.config["executor"]["command_template"].format(task=task)
        timeout = self.config["executor"]["timeout"]

        try:
            output = run_command(command, timeout=timeout)
            duration = int((time.time() - start) * 1000)

            # 扣减额度
            self._decrement_quota()

            return Result(
                task_id=generate_task_id(),
                provider=self.name,
                status="success",
                output=output,
                error=None,
                metadata={
                    "duration_ms": duration,
                    "quota_remaining": self.quota_left()
                },
                raw=None
            )
        except TimeoutError:
            return Result(
                task_id=generate_task_id(),
                provider=self.name,
                status="timeout",
                output="",
                error=f"Execution timed out after {timeout}s",
                metadata={"duration_ms": timeout * 1000},
                raw=None
            )
        except Exception as e:
            return Result(
                task_id=generate_task_id(),
                provider=self.name,
                status="failed",
                output="",
                error=str(e),
                metadata={"duration_ms": int((time.time() - start) * 1000)},
                raw=None
            )

    def _decrement_quota(self):
        current = self.quota_state.get("qoder", {}).get("remaining", 0)
        if current > 0:
            self.quota_state["qoder"]["remaining"] = current - 1
            save_quota_state(self.quota_state)
```

---

## 新增 Provider 流程

接入一个新的 AI 平台，只需要：

```
1. 创建配置文件    → providers/{new_provider}.yaml
2. 实现适配器类    → 继承 Provider，实现 4 个方法（health/authenticated/execute/quota_left）
3. 添加路由规则    → router_rules.yaml 中对应任务类型添加该 Provider
4. 添加关键词      → task_keywords.yaml 中如有新的任务类型，补充关键词
5. 测试            → ai-hub --provider {new_provider} "测试任务"
```

**不需要改的**：Router 代码、Result 格式、存储逻辑、CLI 入口。

---

## 接口稳定性承诺

| 接口 | V0.1 | V0.3 | V0.5 | V1.0 | V2.0 |
|------|------|------|------|------|------|
| `available()` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `health()` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `authenticated()` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `quota_left()` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `execute(task)` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `supports(type)` | 定义不用 | ✅ 用 | ✅ | ✅ | ✅ |
| `cost()` | 定义不用 | 定义不用 | ✅ 用 | ✅ | ✅ |
| `execute(task, context)` | context=null | context=null | context=历史 | context=完整 | ✅ |

**承诺**：已标记 ✅ 的接口签名永不改变。新增参数只能带默认值。
