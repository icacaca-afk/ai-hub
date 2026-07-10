# AI Hub — Quota Manager
# 额度管理层。第一个横切关注点。
#
# 职责：跟踪每个 Provider 的额度消耗，在额度耗尽时通知 Router 降级。
# 位置：core/quota.py（新增文件，不改现有 core/ 文件）
#
# 设计原则：
#   - 不 import 任何 Provider 具体类
#   - 不 import bridge.py
#   - 通过 Router 注入，Provider 代码零修改
#   - SQLite 持久化，进程重启后额度不丢失
#
# API Stability: Experimental（V0.2 新增，V0.3 稳定化）

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Optional


class QuotaManager:
    """Provider 额度管理器。

    用法：
        qm = QuotaManager()
        router = Router(registry, quota_manager=qm)

    Router 注入后自动管理额度：
        - execute() 前检查 is_available()
        - execute() 后调用 consume()（仅成功时）

    Provider 不需要任何修改。
    所有 Provider 初次访问时自动注册到额度表中。
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.path.expanduser("~/.ai-hub/quota.db")
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS quota (
                provider_name TEXT PRIMARY KEY,
                total       INTEGER NOT NULL DEFAULT -1,
                used        INTEGER NOT NULL DEFAULT 0,
                quota_type  TEXT    NOT NULL DEFAULT 'unknown',
                reset_at    TEXT
            )
        """)
        # 使用记录（审计）
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS quota_log (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_name TEXT    NOT NULL,
                amount        INTEGER NOT NULL DEFAULT 1,
                remaining     INTEGER NOT NULL,
                task_id       TEXT,
                created_at    TEXT    NOT NULL
            )
        """)
        self.conn.commit()

    # ── 自动注册 ──

    def ensure(self, provider_name: str, total: int = -1,
               quota_type: str = "unknown") -> None:
        """确保 Provider 已注册到额度表中。

        幂等：已存在则不做任何操作。
        total=-1 表示无限额度。
        """
        self.conn.execute(
            """INSERT OR IGNORE INTO quota (provider_name, total, used, quota_type)
               VALUES (?, ?, 0, ?)""",
            (provider_name, total, quota_type),
        )
        # 如果已存在，更新 total（后续额度调整用）
        if total >= 0:
            self.conn.execute(
                "UPDATE quota SET total = ?, quota_type = ? WHERE provider_name = ? AND total < 0",
                (total, quota_type, provider_name),
            )
        self.conn.commit()

    # ── 查询 ──

    def remaining(self, provider_name: str) -> int:
        """返回剩余额度。-1 = 无限，0 = 已用尽。"""
        row = self._row(provider_name)
        if row is None:
            return -1  # 未注册 → 无限（不阻塞）
        if row["total"] == -1:
            return -1
        return max(0, row["total"] - row["used"])

    def is_available(self, provider_name: str) -> bool:
        """Provider 是否还有额度可用。"""
        return self.remaining(provider_name) != 0

    def exhausted(self, provider_name: str) -> bool:
        """Provider 额度是否已用尽。"""
        rem = self.remaining(provider_name)
        return rem == 0

    # ── 扣减 ──

    def consume(self, provider_name: str, amount: int = 1,
                task_id: str = "") -> bool:
        """扣减额度。返回是否扣减成功。

        事务保护：BEGIN IMMEDIATE → 读 → 检查 → 写 → COMMIT。
        并发安全：原子 UPDATE … WHERE used + ? <= total 替代 SELECT-then-UPDATE。

        无限额度（total == -1）永远返回 True 但不写入日志。
        额度不足（或不满足原子条件）返回 False。
        """
        row = self._row(provider_name)
        if row is None:
            return True  # 未注册 = 无限制
        if row["total"] == -1:
            return True  # 无限额度

        # BEGIN IMMEDIATE：阻止并发写，保证原子性
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            # 原子扣减：WHERE used + ? <= total 防止超扣
            cursor = self.conn.execute(
                "UPDATE quota SET used = used + ? "
                "WHERE provider_name = ? AND used + ? <= total",
                (amount, provider_name, amount),
            )
            if cursor.rowcount == 0:
                self.conn.execute("ROLLBACK")
                return False

            # 读回最新值写日志
            row2 = self._row(provider_name)
            remaining_after = row2["total"] - row2["used"]

            self.conn.execute(
                "INSERT INTO quota_log (provider_name, amount, remaining, task_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (provider_name, amount, remaining_after, task_id,
                 datetime.now().isoformat()),
            )
            self.conn.execute("COMMIT")
            return True
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    # ── 恢复（预留接口） ──

    def reset(self, provider_name: str) -> None:
        """重置某个 Provider 的已用额度为 0。"""
        self.conn.execute(
            "UPDATE quota SET used = 0 WHERE provider_name = ?",
            (provider_name,),
        )
        self.conn.commit()

    def reset_all(self) -> None:
        """重置所有 Provider 的已用额度为 0。"""
        self.conn.execute("UPDATE quota SET used = 0")
        self.conn.commit()

    # ── 状态查询 ──

    def status(self, provider_name: Optional[str] = None) -> list[dict]:
        """返回额度状态列表。不传参返回所有。"""
        if provider_name:
            rows = self.conn.execute(
                "SELECT * FROM quota WHERE provider_name = ?",
                (provider_name,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM quota ORDER BY provider_name").fetchall()

        result = []
        for r in rows:
            remaining = r["total"] if r["total"] == -1 else max(0, r["total"] - r["used"])
            result.append({
                "provider": r["provider_name"],
                "quota_type": r["quota_type"],
                "total": r["total"],
                "used": r["used"],
                "remaining": remaining,
                "exhausted": remaining == 0,
            })
        return result

    def summary(self, provider_name: Optional[str] = None) -> str:
        """友好的额度摘要字符串。"""
        rows = self.status(provider_name)
        if not rows:
            return "No quota data."

        lines = []
        lines.append(f"{'Provider':<16} {'Remaining':>10} {'%':>6} {'Type':<12}")
        lines.append("-" * 48)
        for r in rows:
            pct = " ∞" if r["total"] == -1 else f"{r['remaining']/r['total']*100:.0f}%"
            status_flag = " ⚠ EXHAUSTED" if r["exhausted"] else ""
            lines.append(
                f"{r['provider']:<16} {r['remaining'] if r['remaining'] >= 0 else '∞':>10} "
                f"{pct:>6} {r['quota_type']:<12}{status_flag}"
            )
        return "\n".join(lines)

    def log(self, provider_name: Optional[str] = None, limit: int = 20) -> list[dict]:
        """查询消耗日志。"""
        if provider_name:
            rows = self.conn.execute(
                "SELECT * FROM quota_log WHERE provider_name = ? "
                "ORDER BY id DESC LIMIT ?",
                (provider_name, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM quota_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── 内部 ──

    def _row(self, provider_name: str):
        return self.conn.execute(
            "SELECT * FROM quota WHERE provider_name = ?",
            (provider_name,),
        ).fetchone()

    def close(self) -> None:
        self.conn.close()
