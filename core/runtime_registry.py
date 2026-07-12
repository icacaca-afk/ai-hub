# AI Hub — RuntimeRegistry
# V0.3: Session → Bridge 绑定管理
#
# Session 创建时绑定一个 Bridge 会话（API/CLI/GUI 三类不同）。
# RuntimeRegistry 维护 Session → Bridge 的映射。
# Session.destroy() 时通知 Bridge 释放。
#
# 不修改 Router，不修改 Provider。
#
# API Stability: Experimental（V0.3 新增，V0.4 稳定化）

from __future__ import annotations

from typing import Optional, Dict
from core.bridge import Bridge


class RuntimeRegistry:
    """Session → Bridge 的绑定管理器。

    用法：
        rr = RuntimeRegistry()
        rr.bind(session_id, bridge)
        bridge = rr.get_bridge(session_id)
        rr.unbind(session_id)  # Session.destroy() 时调用
    """

    def __init__(self):
        self._bindings: Dict[str, Bridge] = {}

    def bind(self, session_id: str, bridge: Bridge) -> None:
        """绑定 Session 和 Bridge。

        如果 Session 已绑定其他 Bridge，覆盖旧绑定。
        """
        self._bindings[session_id] = bridge

    def get_bridge(self, session_id: str) -> Optional[Bridge]:
        """获取 Session 绑定的 Bridge。返回 None 如果未绑定。"""
        return self._bindings.get(session_id)

    def unbind(self, session_id: str) -> bool:
        """解除绑定。

        Returns:
            True 如果成功解除，False 如果原本未绑定
        """
        if session_id in self._bindings:
            del self._bindings[session_id]
            return True
        return False

    def is_bound(self, session_id: str) -> bool:
        """Session 是否已绑定 Bridge。"""
        return session_id in self._bindings

    def active_sessions(self) -> list[str]:
        """返回所有已绑定 Bridge 的 Session ID 列表。"""
        return list(self._bindings.keys())

    def count(self) -> int:
        """返回活跃绑定数。"""
        return len(self._bindings)

    def clear(self) -> int:
        """解除所有绑定。返回解除的数量。"""
        n = len(self._bindings)
        self._bindings.clear()
        return n
