# AI Hub — Result
# 统一结果格式，所有 Provider 的 execute() 必须返回此对象

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Result:
    """统一结果格式。

    所有 Provider 的 execute() 必须返回此对象。
    这是整个项目最核心的数据结构之一。
    """

    provider: str                           # 执行该任务的 Provider 名称
    status: str                             # success / failed / timeout / partial
    output: str                             # 任务输出内容；失败时为错误描述
    error: str | None = None                # 错误详情；成功时为 None
    metadata: dict[str, Any] = field(default_factory=dict)  # 执行元数据

    def __post_init__(self):
        # 校验 status 必须是合法值
        valid = {"success", "failed", "timeout", "partial"}
        if self.status not in valid:
            raise ValueError(
                f"Invalid status '{self.status}', must be one of {valid}"
            )

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（用于 JSON 持久化）。"""
        return {
            "provider": self.provider,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Result:
        """从字典反序列化。"""
        return cls(
            provider=data["provider"],
            status=data["status"],
            output=data["output"],
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )

    def __str__(self) -> str:
        """用户友好的字符串输出。"""
        if self.is_success:
            return self.output
        return f"[{self.status}] {self.error or self.output}"
