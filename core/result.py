# AI Hub — Result
# 统一结果格式，所有 Bridge 执行后返回此对象
#
# API Stability: Stable

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Result:
    """统一结果格式。

    所有 Bridge 执行后返回此对象。
    output 永远是纯文本，产物文件走 artifacts。

    API Stability: Stable
    """

    provider: str                           # 执行该任务的 Provider 名称
    status: str                             # success / failed / timeout / partial
    output: str                             # 纯文本输出；失败时为错误描述
    error: str | None = None                # 错误详情；成功时为 None
    artifacts: list[str] = field(default_factory=list)  # 产物文件路径列表（截图/PDF/代码文件等）
    metadata: dict[str, Any] = field(default_factory=dict)  # 执行元数据

    def __post_init__(self):
        valid = {"success", "failed", "timeout", "partial"}
        if self.status not in valid:
            raise ValueError(
                f"Invalid status '{self.status}', must be one of {valid}"
            )

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "artifacts": self.artifacts,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Result:
        return cls(
            provider=data["provider"],
            status=data["status"],
            output=data["output"],
            error=data.get("error"),
            artifacts=data.get("artifacts", []),
            metadata=data.get("metadata", {}),
        )

    def __str__(self) -> str:
        if self.is_success:
            parts = [self.output]
            if self.artifacts:
                parts.append(f"\n[Artifacts] {', '.join(self.artifacts)}")
            return "\n".join(parts)
        return f"[{self.status}] {self.error or self.output}"
