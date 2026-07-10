# AI Hub — RuntimeRegistry
# Runtime 注册中心：管理 Runtime 类型 → Bridge 类的映射
#
# 设计原则：
#   - Runtime 可以动态注册
#   - Provider 不知道 Runtime，Runtime 决定使用哪种 Bridge
#   - Router 不修改
#
# 使用方式：
#   reg = RuntimeRegistry.default()
#   bridge = reg.create_bridge("browser", headless=False)
#   # 或者注册自定义 Runtime
#   reg.register("my_runtime", MyBridge, custom_param="default")
#
# API Stability: Experimental

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from core.bridge import Bridge


@dataclass
class Runtime:
    """Runtime 描述符。

    一个 Runtime 对应一种 Bridge 类型及其默认配置。
    """

    name: str                               # 唯一标识符，如 "browser"
    bridge_cls: type[Bridge]                # 对应的 Bridge 类
    description: str = ""                   # 一句话描述
    default_config: dict[str, Any] = field(default_factory=dict)  # 默认配置


class RuntimeRegistry:
    """Runtime 注册中心。

    管理 Runtime 类型 → Bridge 类的映射。
    Provider 可以通过 RuntimeRegistry 动态获取 Bridge，
    而不需要直接实例化具体的 Bridge 类。

    不修改 Router。Provider 可选使用。

    API Stability: Experimental
    """

    _instance: RuntimeRegistry | None = None

    def __init__(self):
        self._runtimes: Dict[str, Runtime] = {}

    @classmethod
    def default(cls) -> RuntimeRegistry:
        """获取默认单例，自动注册内置 Runtime 类型。"""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._register_defaults()
        return cls._instance

    def _register_defaults(self):
        """注册内置 Runtime 类型。"""
        from core.bridge import (
            FakeBridge,
            CLIBridge,
            APIBridge,
            GUIBridge,
            BrowserBridge,
        )

        self.register("fake", FakeBridge, description="Fake runtime for testing")
        self.register("cli", CLIBridge, description="CLI subprocess runtime")
        self.register("api", APIBridge, description="HTTP API runtime")
        self.register("gui", GUIBridge, description="GUI automation runtime (pyautogui)")
        self.register("browser", BrowserBridge, description="Browser automation runtime (Playwright)")

    def register(
        self,
        name: str,
        bridge_cls: type[Bridge],
        description: str = "",
        **default_config,
    ) -> None:
        """注册一个 Runtime 类型。

        Args:
            name: Runtime 名称
            bridge_cls: 对应的 Bridge 类
            description: 一句话描述
            **default_config: Bridge 默认配置
        """
        if name in self._runtimes:
            raise ValueError(f"Runtime '{name}' is already registered")
        self._runtimes[name] = Runtime(
            name=name,
            bridge_cls=bridge_cls,
            description=description,
            default_config=default_config,
        )

    def unregister(self, name: str) -> bool:
        """注销一个 Runtime 类型。"""
        if name in self._runtimes:
            del self._runtimes[name]
            return True
        return False

    def get(self, name: str) -> Runtime | None:
        """获取 Runtime 描述符。"""
        return self._runtimes.get(name)

    def create_bridge(self, name: str, **config) -> Bridge:
        """根据 Runtime 名称创建对应的 Bridge 实例。

        合并默认配置和传入的配置（传入优先）。

        Args:
            name: Runtime 名称
            **config: 覆盖默认配置的参数

        Returns:
            Bridge 实例

        Raises:
            ValueError: 如果 Runtime 未注册
        """
        runtime = self.get(name)
        if runtime is None:
            raise ValueError(
                f"Runtime '{name}' not registered. "
                f"Available: {self.available_types()}"
            )
        merged = {**runtime.default_config, **config}
        return runtime.bridge_cls(**merged)

    def available_types(self) -> list[str]:
        """返回所有已注册的 Runtime 名称。"""
        return list(self._runtimes.keys())

    def all(self) -> list[Runtime]:
        """返回所有已注册的 Runtime 描述符。"""
        return list(self._runtimes.values())

    def check_available(self, name: str) -> bool:
        """检查某个 Runtime 是否可用（创建 Bridge 并检查 check_available）。"""
        runtime = self.get(name)
        if runtime is None:
            return False
        try:
            bridge = self.create_bridge(name)
            return bridge.check_available()
        except Exception:
            return False

    def available_runtimes(self) -> list[str]:
        """返回所有当前可用的 Runtime 名称。"""
        return [name for name in self._runtimes if self.check_available(name)]

    def __repr__(self) -> str:
        return f"<RuntimeRegistry runtimes={self.available_types()}>"
