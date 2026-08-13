# AI Hub — Provider 规范

[English](PROVIDER_SPEC.md) | [简体中文](PROVIDER_SPEC.zh-CN.md)

> Provider 契约：Stable · Health Observation：V0.6+ · 按 V1.0.11 更新

## 职责边界

Provider 声明身份、Capability、路由偏好并选择 Bridge。Bridge 负责与外部 Runtime
通信。

```text
Task → Provider.select_bridge(Task) → Bridge.run(Task) → BridgeResult → Result
```

Provider 不得自行实现 `execute()` 通信路径，也不得在基础 Router 中加入识别特定
Provider 的分支。

## 必备声明

```python
from core.bridge import CLIBridge
from core.health import HealthReport
from core.provider import Provider, ProviderMetadata


class YourProvider(Provider):
    metadata = ProviderMetadata(
        name="your_platform",
        display_name="Your Platform",
        description="一句话描述 Runtime",
        version="0.1.0",
        capabilities=["code.generate", "text.summarize"],
        priority=80,
        fallback=["demo"],
        quota_type="unknown",
        quota_total=-1,
        health_type="cli",
    )

    bridge = CLIBridge(
        command="your-cli",
        version_command="your-cli --version",
        command_template='your-cli "{task}"',
    )

    def health(self) -> HealthReport:
        if self.bridge.check_available():
            return HealthReport.healthy(
                self.name,
                authenticated=self.authenticated(),
                quota_ok=self.quota_left() != 0,
            )
        return HealthReport.unavailable(
            self.name,
            message="your-cli 未安装或不在 PATH 中",
        )

    def authenticated(self) -> bool:
        return self.bridge.check_available()

    def quota_left(self) -> int:
        return -1
```

部分遗留 Provider 的 `health()` 仍返回 `bool`，Health Framework 会统一升级这个
结果。新 Provider 应返回 `HealthReport`，从而保留 healthy、degraded、unknown、
unavailable 四态和诊断信息。

## ProviderMetadata

| 字段 | 类型 | 含义 |
|---|---|---|
| `name` | `str` | 稳定的唯一标识符 |
| `display_name` | `str` | 人类可读名称 |
| `description` | `str` | Adapter 简短描述 |
| `version` | `str` | Adapter 版本 |
| `capabilities` | `list[str]` | 已注册的 Capability 标签 |
| `priority` | `int` | 静态路由优先级，数值越大越优先 |
| `fallback` | `list[str]` | Provider 名称降级顺序 |
| `quota_type` | `str` | `daily`、`monthly`、`unlimited` 或 `unknown` |
| `quota_total` | `int` | 声明额度；`-1` 表示无限或未知 |
| `quota_auto_detect` | `bool` | 是否能自动检测额度 |
| `health_type` | `str` | `cli`、`api`、`browser`、`mcp` 或空值 fallback |
| `cost_currency` | `str \| None` | 可选成本货币 |
| `cost_amount` | `float` | 可选成本数值 |
| `cost_unit` | `str` | 成本单位，通常是 `per_call` |
| `timeout` | `int` | 单次调用超时秒数 |
| `retry_count` | `int` | Provider 层重试次数 |
| `retry_delay` | `float` | Provider 重试间隔 |

## 行为要求

- `select_bridge(task)` 返回 Bridge。Provider 只有一个 class-level `bridge` 时，
  继承的实现已经足够。
- `authenticated()` 返回布尔观察结果，不得弹出交互提示。
- `quota_left()` 在额度耗尽时返回 `0`，无法得知数字上限时返回 `-1`。
- `health()` 应有时间边界、包含诊断信息，并能安全用于 `status` 或路由健康检查。
- 所有声明的 Capability 必须存在于 `core.capabilities.CAPABILITIES`。

## Bridge 契约

```python
class Bridge(ABC):
    def run(self, task: Task, **kwargs) -> BridgeResult: ...
    def check_available(self) -> bool: ...
```

`BridgeResult` 包含 `success`、`output`、`error`、`duration_ms`、`artifacts` 和
`raw`，不包含 Provider 字段。

尽量复用现有 Bridge。新增通信抽象或修改 `core/bridge.py` 会跨越冻结 Core 边界，
必须先写 ADR。Provider 通信不得在 Bridge 实现之外另建平行 Transport Path。

## 接入与测试

1. 创建 `providers/<name>/__init__.py` 和 `provider.py`。
2. 从包中导出 Provider 类。
3. 如果 CLI 还没有自动发现机制，在 Runtime Registry 构造路径中注册。
4. 在 `tests/test_provider_contract.py` 添加 Provider Contract Test。
5. 把类加入 `test_capability_metadata_consistency`。
6. 添加不依赖真实 Runtime 的 Health/Authentication 定向测试。
7. 先跑 Provider Contract Test，再跑不含 Live Provider 的全量回归。

现有 Provider 实现除有依据的 Bug Fix 外保持冻结。新 Provider 应进入新目录，不得
修改 Core 或基础 Router 行为。
