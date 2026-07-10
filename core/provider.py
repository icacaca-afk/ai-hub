# AI Hub — Provider 基类
# 整个项目最核心的接口。所有 AI 平台适配器必须继承此类。
#
# 设计原则：
# 1. 接口稳定：一旦定义，长期不变。新增参数只能带默认值。
# 2. 简单优先：第一版只有 4 个必须实现的方法。
# 3. 渐进演进：预留 supports() 和 cost()，第一版不用但不影响。

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.result import Result


class Provider(ABC):
    """所有 AI 平台适配器的基类。

    新增一个 Provider 只需要：
    1. 继承此类
    2. 实现 4 个抽象方法
    3. 创建对应的 YAML 配置文件
    不需要修改 Router、CLI 或其他 Provider 的代码。
    """

    # ─── 元信息（子类必须定义）───
    name: str = ""                    # 唯一标识符，如 "qoder"
    display_name: str = ""            # 用户可见名称，如 "QODER"
    description: str = ""             # 一句话描述
    version: str = "0.0.1"            # Provider 适配器版本

    # ─── 能力描述（子类必须定义）───
    capabilities: list[str] = []      # 能力标签，如 ["coding", "debug"]
    task_types: list[str] = []        # 支持的任务类型，如 ["coding"]

    # ─── 路由信息（子类必须定义）───
    priority: int = 0                 # 同任务类型下的优先级，越大越优先
    fallback: list[str] = []          # 不可用时的降级 Provider 名称链

    # ─── 状态检查 ───

    def available(self) -> bool:
        """检查 Provider 是否可用（健康 + 登录 + 额度三者均通过）。

        子类可以重写此方法以自定义检查逻辑，
        但默认实现已经覆盖了大多数场景。
        """
        return self.health() and self.authenticated() and self.quota_left() != 0

    @abstractmethod
    def health(self) -> bool:
        """检查 Provider 服务是否在线。

        Returns:
            True 如果服务可用，False 否则。
        """
        ...

    @abstractmethod
    def authenticated(self) -> bool:
        """检查用户是否已登录。

        Returns:
            True 如果已登录，False 否则。
        """
        ...

    # ─── 额度管理 ───

    @abstractmethod
    def quota_left(self) -> int:
        """返回剩余免费额度（次数）。

        Returns:
            剩余次数；无限制返回 -1；不可用返回 0。
        """
        ...

    def quota_info(self) -> dict[str, Any]:
        """返回额度详情。

        子类可以重写此方法以提供更详细的额度信息。
        """
        remaining = self.quota_left()
        return {
            "type": "unknown",
            "total": -1,
            "remaining": remaining,
            "reset_at": None,
            "auto_detect": False,
        }

    # ─── 执行 ───

    @abstractmethod
    def execute(self, task: str, context: dict[str, Any] | None = None) -> Result:
        """执行任务，返回统一格式的结果。

        Args:
            task: 用户的任务描述（自然语言）。
            context: 可选的上下文信息（历史记录、文件路径等）。
                     第一版不使用，但接口预留。

        Returns:
            Result 对象。
        """
        ...

    # ─── 预留接口（第一版不用，但已定义）───

    def supports(self, task_type: str) -> bool:
        """判断是否支持某任务类型。

        V0.3 的 AI Router 可直接调用此方法。
        """
        return task_type in self.task_types

    def cost(self) -> dict[str, Any]:
        """返回单次调用成本。

        V0.5+ 的成本优化路由可调用此方法。

        Returns:
            {"currency": "CNY"/"USD"/None, "amount": float, "unit": "per_call"/"per_token"}
        """
        return {
            "currency": None,
            "amount": 0.0,
            "unit": "per_call",
        }

    # ─── 工具方法 ───

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} priority={self.priority}>"
