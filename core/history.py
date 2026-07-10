# AI Hub — History Store
# 任务执行历史记录，JSONL 格式持久化

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class HistoryStore:
    """任务历史记录存储。

    使用 JSONL 格式（每行一个 JSON 对象），无需数据库。
    V0.5+ 可升级为 SQLite。
    """

    def __init__(self, filepath: str = "history/tasks.jsonl"):
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self.filepath.exists():
            self.filepath.touch()

    def add(
        self,
        task: str,
        task_type: str,
        provider: str,
        result: Any,
    ) -> None:
        """追加一条任务记录。

        Args:
            task: 用户输入的任务描述
            task_type: 路由判断的任务类型
            provider: 执行该任务的 Provider 名称
            result: Result 对象
        """
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "input": task,
            "task_type": task_type,
            "provider": provider,
            "status": result.status,
            "duration_ms": result.metadata.get("duration_ms", 0),
            "output_preview": result.output[:200] if result.output else "",
        }

        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def recent(self, limit: int = 10) -> list[dict]:
        """返回最近的 N 条记录。"""
        lines = self.filepath.read_text(encoding="utf-8").strip().splitlines()
        records = []
        for line in reversed(lines):
            if line.strip():
                records.append(json.loads(line))
            if len(records) >= limit:
                break
        return records
