# AI Hub — Session / SessionManager
# V0.3: Runtime 生命周期管理
#
# Session 是跨多次 Task 的上下文容器。
# 所有 Bridge 都有 Session 概念，不只是 GUIBridge。
#
# API Stability: Experimental（V0.3 新增，V0.4 稳定化）

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Session:
    """一个跨多次 Task 的上下文容器。

    生命周期：create → (checkpoint → resume)* → destroy

    Attributes:
        session_id: 唯一标识
        provider_name: 绑定的 Provider 名称
        created_at: 创建时间戳
        updated_at: 最后更新时间戳
        status: active / checkpointed / destroyed
        context: 跨 Task 上下文（键值对）
    """
    session_id: str
    provider_name: str
    created_at: float
    updated_at: float
    status: str = "active"
    context: dict = field(default_factory=dict)

    def is_active(self) -> bool:
        return self.status == "active"

    def is_checkpointed(self) -> bool:
        return self.status == "checkpointed"

    def is_destroyed(self) -> bool:
        return self.status == "destroyed"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Session:
        return cls(**d)


class SessionManager:
    """Session 的创建/查询/Checkpoint/Resume/Destroy 中心。

    不修改 Router。不修改 Provider。
    Bridge 可以请求 Session（用于跨调用状态），但 Router 不感知。

    持久化：JSON 文件（~/.ai-hub/sessions.json）
    """

    def __init__(self, db_dir: Optional[str] = None):
        if db_dir is None:
            db_dir = os.path.expanduser("~/.ai-hub")
        os.makedirs(db_dir, exist_ok=True)
        self._db_path = os.path.join(db_dir, "sessions.json")
        self._sessions: dict[str, Session] = {}
        self._load()

    # ── 创建 ──

    def create(self, provider_name: str,
               context: Optional[dict] = None) -> Session:
        """创建新 Session。

        Args:
            provider_name: 绑定的 Provider 名称
            context: 初始上下文（可选）

        Returns:
            新建的 Session 对象
        """
        now = time.time()
        session = Session(
            session_id=str(uuid.uuid4()),
            provider_name=provider_name,
            created_at=now,
            updated_at=now,
            status="active",
            context=context or {},
        )
        self._sessions[session.session_id] = session
        self._save()
        return session

    # ── 查询 ──

    def get(self, session_id: str) -> Optional[Session]:
        """获取 Session。返回 None 如果不存在。"""
        return self._sessions.get(session_id)

    def list(self, provider_name: Optional[str] = None) -> list[Session]:
        """列出 Session。可按 Provider 过滤。"""
        sessions = list(self._sessions.values())
        if provider_name:
            sessions = [s for s in sessions if s.provider_name == provider_name]
        return sorted(sessions, key=lambda s: s.updated_at, reverse=True)

    # ── Checkpoint ──

    def checkpoint(self, session_id: str,
                   context: Optional[dict] = None) -> Session:
        """保存 Session 当前状态。

        - 可选合并新 context
        - 状态变为 checkpointed
        - 持久化到磁盘

        Returns:
            更新后的 Session

        Raises:
            KeyError: Session 不存在
            ValueError: Session 已 destroyed
        """
        session = self._require(session_id)
        if session.is_destroyed():
            raise ValueError(f"Session {session_id} is destroyed")

        if context:
            session.context.update(context)

        session.status = "checkpointed"
        session.updated_at = time.time()
        self._save()
        return session

    # ── Resume ──

    def resume(self, session_id: str) -> Session:
        """恢复 checkpointed 的 Session。

        - 状态变为 active
        - 更新时间戳

        Returns:
            恢复后的 Session

        Raises:
            KeyError: Session 不存在
            ValueError: Session 不是 checkpointed 状态
        """
        session = self._require(session_id)
        if session.is_destroyed():
            raise ValueError(f"Session {session_id} is destroyed")
        if not session.is_checkpointed():
            raise ValueError(f"Session {session_id} is {session.status}, not checkpointed")

        session.status = "active"
        session.updated_at = time.time()
        self._save()
        return session

    # ── Destroy ──

    def destroy(self, session_id: str) -> bool:
        """销毁 Session。

        - 状态变为 destroyed
        - 保留记录（审计），但从活跃列表移除
        - 后续 get() 仍可访问（状态为 destroyed）

        Returns:
            True 如果成功销毁，False 如果不存在或已 destroyed
        """
        session = self._sessions.get(session_id)
        if session is None or session.is_destroyed():
            return False

        session.status = "destroyed"
        session.updated_at = time.time()
        self._save()
        return True

    # ── 内部 ──

    def _require(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Session not found: {session_id}")
        return session

    def _save(self) -> None:
        data = {sid: s.to_dict() for sid, s in self._sessions.items()}
        with open(self._db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self) -> None:
        if not os.path.exists(self._db_path):
            return
        try:
            with open(self._db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for sid, d in data.items():
                self._sessions[sid] = Session.from_dict(d)
        except (json.JSONDecodeError, TypeError):
            pass  # 损坏文件，忽略

    def close(self) -> None:
        self._save()
