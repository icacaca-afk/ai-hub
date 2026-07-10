# AI Hub — Provider 基类（V0.0.5 重构）
#
# 核心变更：
# 1. 引入 ProviderMetadata 数据类——声明式描述 Provider 能力
# 2. 引入 Bridge——Provider 只声明通信方式，Bridge 负责执行
# 3. 能力系统从 task_types 改为 capabilities（命名空间格式）
# 4. Provider 实现只需 ~30 行：定义 metadata + 选 bridge + 4 个方法
#
# API 稳定性：Provider API = Stable，Bridge API = Experimental

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.bridge import Bridge, BridgeResult
from core.result import Result


@dataclass
class ProviderMetadata:
    """Provider 元信息声明。

    每个 Provider 必须定义一个 ProviderMetadata 实例。
    这是 Provider 对外暴露的全部信息，Router 和 Registry 只读这些字段。
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


class Provider(ABC):
    """所有 AI 平台适配器的基类。

    新增一个 Provider 只需要：
    1. 定义 metadata（ProviderMetadata）
    2. 选择 bridge（CLIBridge / APIBridge / FakeBridge）
    3. 实现 4 个方法（health / authenticated / quota_left / execute）

    不需要修改 Router、CLI、Registry 或其他 Provider 的代码。

    Provider API: Stable（接口签名不再变化）
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

    # ─── 执行 ───

    @abstractmethod
    def execute(self, task: str, context: dict[str, Any] | None = None) -> Result:
        """执行任务，返回统一格式的 Result。"""
        ...

    # ─── 预留接口 ───

    def supports(self, capability: str) -> bool:
        """判断是否支持某能力标签。

        Provider API: Stable
        """
        return capability in self.metadata.capabilities

    def cost(self) -> dict[str, Any]:
        """返回单次调用成本。

        Provider API: Stable (预留)
        """
        return {
            "currency": self.metadata.cost_currency,
            "amount": self.metadata.cost_amount,
            "unit": self.metadata.cost_unit,
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

    # ─── Bridge 辅助 ───

    def _run_bridge(self, task: str, **kwargs) -> BridgeResult:
        """调用 bridge 执行，返回 BridgeResult。

        子类在 execute() 中调用此方法，
        然后把 BridgeResult 转换为 Result。
        """
        return self.bridge.run(task, **kwargs)

    @staticmethod
    def _bridge_to_result(br: BridgeResult, provider_name: str) -> Result:
        """将 BridgeResult 转换为统一的 Result。"""
        return Result(
            provider=provider_name,
            status="success" if br.success else "failed",
            output=br.output,
            error=br.error,
            metadata={
                "duration_ms": br.duration_ms,
            },
        )
