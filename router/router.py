# AI Hub — Router（V0.1 规则路由）
#
# 第一版用关键词匹配判断任务类型，再用优先级选择 Provider。
# 不使用 AI 做路由决策。
#
# V0.3 会升级为 AI 路由，但 Provider 接口和 Result 格式不变。

from __future__ import annotations

from typing import Any

from core.provider import Provider
from core.registry import ProviderRegistry
from core.result import Result


# ─── 任务类型关键词映射 ───
# 第一版用简单的关键词匹配。V0.3 会替换为 LLM 分类。
TASK_KEYWORDS: dict[str, list[str]] = {
    "coding": [
        "写代码", "写一个", "实现", "开发", "重构", "调试", "bug",
        "函数", "类", "api", "deploy", "部署", "脚本", "python",
        "javascript", "java", "html", "css", "sql",
        "code", "function", "class", "refactor",
    ],
    "analysis": [
        "总结", "分析", "摘要", "提取", "读", "看看", "review",
        "pdf", "文档", "报告", "summarize", "analyze",
    ],
    "search": [
        "搜索", "搜一下", "查一下", "查一查", "查找", "找一下",
        "search", "look up",
    ],
    "file_ops": [
        "整理", "移动", "重命名", "压缩", "清理", "文件",
        "file", "organize", "clean",
    ],
    "general": [
        "翻译", "写邮件", "起名字", "建议", "help", "你好",
        "hello", "hi", "问",
    ],
}


def classify_task(task: str) -> str:
    """通过关键词匹配判断任务类型。

    Args:
        task: 用户的任务描述

    Returns:
        任务类型字符串，如 "coding", "search", "general"
    """
    task_lower = task.lower()
    scores: dict[str, int] = {}

    for task_type, keywords in TASK_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in task_lower)
        if score > 0:
            scores[task_type] = score

    if not scores:
        return "general"

    # 返回匹配关键词最多的类型
    return max(scores, key=scores.get)


class Router:
    """规则路由器。

    根据任务类型 + Provider 优先级 + 可用性选择最合适的 Provider。
    """

    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def route(self, task: str) -> tuple[str, Provider | None]:
        """为任务选择最合适的 Provider。

        Args:
            task: 用户的任务描述

        Returns:
            (task_type, provider) 元组。
            如果没有可用 Provider，provider 为 None。
        """
        task_type = classify_task(task)
        candidates = self.registry.find_available(task_type)

        if candidates:
            # find_available 已按 priority 降序排列，取第一个
            return task_type, candidates[0]

        # 所有候选都不可用，尝试 fallback
        all_providers = self.registry.find_by_task_type(task_type)
        for p in all_providers:
            for fb_name in p.fallback:
                fb = self.registry.get(fb_name)
                if fb and fb.available():
                    return task_type, fb

        return task_type, None

    def execute(self, task: str) -> Result:
        """路由并执行任务。

        Args:
            task: 用户的任务描述

        Returns:
            Result 对象。如果没有可用 Provider，返回 failed 结果。
        """
        task_type, provider = self.route(task)

        if provider is None:
            return Result(
                provider="none",
                status="failed",
                output="",
                error=f"No available provider for task type '{task_type}'",
                metadata={"task_type": task_type},
            )

        return provider.execute(task)
