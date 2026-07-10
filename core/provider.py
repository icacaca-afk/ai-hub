# AI Hub — Provider 基类（V0.0.6 冻结版）
#
# Provider 是能力描述与选择策略的声明，不负责执行。
# 执行交给 Bridge。Provider 通过 select_bridge() 告诉 Router 用哪个 Bridge。
#
# Provider 接口：
#   - metadata: ProviderMetadata（声明能力、优先级、降级链）
#   - health() / authenticated() / quota_left(): 状态检查
#   - select_bridge(task): 选择 Bridge（返回 Bridge 实例）
#   - supports(capability): 是否支持某能力
#
# Provider 不实现 execute()。执行由 Router 调 bridge.run() 完成。
#
# API Stability: Stable

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.bridge import Bridge
from core.task import Task


@dataclass
class ProviderMetadata:
    """Provider 元信息声明。

    每个 Provider 必须定义一个 ProviderMetadata 实例。
    这是 Provider 对外暴露的全部信息，Router 和 CapabilityRegistry 只读这些字段。

    API Stability: Stable
    """

    name: str                           # 唯一标识符，如 "qoder"
    display_name: str                   # 用户可见名称
    description: str                    # 一句话描述
    version: str = "0.0.1"              # 适配器版本

    # 能力标签（命名空间格式：domain.action）
    capabilities: list[str] = field(default_factory=list)

    # 路由配置
    priority: int = 0                   # 同能力下的优先级，越大越优先
    fallback: list[str] = field(default_factory=list)  # 降级链

    # 额度配置
    quota_type: str = "unknown"         # daily / monthly / unlimited / unknown
    quota_total: int = -1               # 总额度，-1 表示无限制
    quota_auto_detect: bool = False     # 是否自动检测额度

    # 成本（预留）
    cost_currency: str | None = None
    cost_amount: float = 0.0
    cost_unit: str = "per_call"

    # 执行控制
    timeout: int = 300                       # 单次执行超时（秒）
    retry_count: int = 0                     # 失败重试次数（0 = 不重试）
    retry_delay: float = 1.0                 # 重试间隔（秒）


class Provider(ABC):
    """所有 AI 平台适配器的基类。

    Provider 只负责声明能力和选择 Bridge，不负责执行。
    执行由 Router 调用 Bridge.run() 完成。

    新增一个 Provider 只需要：
    1. 定义 metadata（ProviderMetadata）
    2. 选择 bridge（CLIBridge / APIBridge / FakeBridge）
    3. 实现 3 个方法（health / authenticated / quota_left）
    4. 实现 select_bridge(task)（大多数情况直接返回 self.bridge）

    不需要修改 Router、CLI、CapabilityRegistry 或其他 Provider 的代码。

    **新增 Provider 不允许修改 Router。**

    API Stability: Stable
    """

    # 子类必须定义
    metadata: ProviderMetadata

    # 子类必须选择一个 Bridge
    bridge: Bridge

    # ─── 状态检查 ───

    def available(self) -> bool:
        """检查 Provider 是否可用（Bridge 可用 + 已认证 + 有额度）。"""
        return (
            self.bridge.check_available()
            and self.authenticated()
            and self.quota_left() != 0
        )

    @abstractmethod
    def health(self) -> bool:
        """检查服务是否在线。"""
        ...

    @abstractmethod
    def authenticated(self) -> bool:
        """检查用户是否已登录。"""
        ...

    # ─── 额度管理 ───

    @abstractmethod
    def quota_left(self) -> int:
        """返回剩余免费额度。-1 = 无限制，0 = 不可用。"""
        ...

    def quota_info(self) -> dict[str, Any]:
        return {
            "type": self.metadata.quota_type,
            "total": self.metadata.quota_total,
            "remaining": self.quota_left(),
            "reset_at": None,
            "auto_detect": self.metadata.quota_auto_detect,
        }

    # ─── Bridge 选择 ───

    def select_bridge(self, task: Task) -> Bridge:
        """选择用于执行此任务的 Bridge。

        大多数 Provider 只有一个 Bridge，直接返回 self.bridge。
        如果一个 Provider 支持多种通信方式，可以根据 task 选择不同的 Bridge。

        Args:
            task: 任务对象

        Returns:
            Bridge 实例
        """
        return self.bridge

    # ─── 能力查询 ───

    def supports(self, capability: str) -> bool:
        """判断是否支持某能力标签。"""
        return capability in self.metadata.capabilities

    def cost(self) -> dict[str, Any]:
        """返回单次调用成本（预留）。"""
        return {
            "currency": self.metadata.cost_currency,
            "amount": self.metadata.cost_amount,
            "unit": self.metadata.cost_unit,
        }

    # ─── 任务估算 ───

    def estimate(self, task: Task) -> dict[str, Any]:
        """估算任务执行的成本和时间。

        在实际执行前调用，用于路由决策和用户提示。
        子类可覆盖以提供更精确的估算。

        Args:
            task: 任务对象

        Returns:
            估算信息字典，包含：
            - duration_ms_est: 预估执行时间（毫秒）
            - cost: 成本信息（同 cost() 返回）
            - retry_count: 重试次数
            - retry_delay: 重试间隔（秒）
            - timeout: 超时时间（秒）
        """
        return {
            "duration_ms_est": self.metadata.timeout * 1000,
            "cost": self.cost(),
            "retry_count": self.metadata.retry_count,
            "retry_delay": self.metadata.retry_delay,
            "timeout": self.metadata.timeout,
        }

    # ─── 工具方法 ───

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def display_name(self) -> str:
        return self.metadata.display_name

    @property
    def capabilities(self) -> list[str]:
        return self.metadata.capabilities

    @property
    def priority(self) -> int:
        return self.metadata.priority

    @property
    def fallback(self) -> list[str]:
        return self.metadata.fallback

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} caps={self.capabilities}>"
