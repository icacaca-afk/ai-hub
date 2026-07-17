# AI Hub — Planner Prompts
# V0.9.2: LLM Planner 的 Prompt 模板（独立文件）
#
# ADR-0015: Prompt 放独立文件，便于 V0.9.3 explain-plan / V0.10 planner cache /
# V1.0 Prompt Version 复用，避免后续拆分成本。
#
# V0.9.2 使用硬编码模板（不可配置）。未来 V1.0+ 可考虑用户可配置化。
#
# API Stability: Experimental

from __future__ import annotations

from core.capabilities import CAPABILITIES


# 可用 capability 列表（注入 prompt 供 LLM 选择）
_AVAILABLE_CAPABILITIES = ", ".join(sorted(CAPABILITIES.keys()))


# 任务分解 Prompt 模板
# 要求 LLM 返回 JSON 数组，每个元素含 content / capabilities / depends_on
DECOMPOSE_PROMPT_TEMPLATE = """你是任务分解器。把以下任务分解为有序步骤。

任务：{task_content}

可用能力标签：{capabilities_list}

返回 JSON 数组，每个元素含：
- content: 步骤描述（自然语言）
- capabilities: 能力标签列表（从可用标签中选）
- depends_on: 依赖的前置步骤索引（如 ["step-0"]），无依赖则空数组

只返回 JSON，不要其他文字。"""


def build_decompose_prompt(task_content: str) -> str:
    """构造任务分解 prompt。

    Args:
        task_content: 原始任务描述

    Returns:
        完整的 prompt 字符串
    """
    return DECOMPOSE_PROMPT_TEMPLATE.format(
        task_content=task_content,
        capabilities_list=_AVAILABLE_CAPABILITIES,
    )
