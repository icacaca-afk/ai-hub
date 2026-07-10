# AI Hub — Task 输入 dataclass
# 所有任务在系统内流转的统一输入格式
#
# 用户输入 → Task → Router → Capability → Provider → Bridge → Result
#
# API Stability: Stable

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.capabilities import classify


@dataclass
class Task:
    """统一任务输入格式。

    用户提交的请求在进入 Router 之前会被包装为 Task。
    Task 携带任务内容、识别出的能力标签、上下文和输入产物。

    API Stability: Stable
    """

    content: str                                       # 用户的任务描述（自然语言）
    task_id: str = ""                                  # 唯一标识符（空则自动生成）
    capabilities: list[str] = field(default_factory=list)  # 识别出的能力标签
    context: dict[str, Any] = field(default_factory=dict)  # 上下文（历史记录、文件路径等）
    artifacts: list[str] = field(default_factory=list)     # 输入产物文件路径（PDF/图片等）

    def __post_init__(self):
        if not self.task_id:
            import uuid
            self.task_id = uuid.uuid4().hex[:12]
        if not self.capabilities:
            self.capabilities = classify(self.content)

    @classmethod
    def from_text(cls, text: str, **kwargs) -> Task:
        """从纯文本创建 Task，自动识别能力标签。"""
        return cls(content=text, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "content": self.content,
            "capabilities": self.capabilities,
            "context": self.context,
            "artifacts": self.artifacts,
        }
