# AI Hub — Capability 系统
# 能力标签定义 + 关键词到能力的映射
#
# 路由链路：
#   Task → 关键词匹配 → Capability → Registry 查找 → Provider
#
# Provider 声明自己支持哪些 capability，Router 按 capability 查找 Provider。
# 新增 Provider 不需要改 Router。

from __future__ import annotations


# ─── 能力标签定义 ───
# 采用命名空间格式：domain.action
# 这样以后可以细分而不冲突，例如 code.generate / code.review / code.debug
CAPABILITIES = {
    "code.generate":    "生成代码",
    "code.debug":       "调试代码",
    "code.refactor":    "重构代码",
    "code.review":      "代码审查",
    "text.summarize":   "总结文本",
    "text.analyze":     "分析文本",
    "text.translate":   "翻译文本",
    "text.generate":    "生成文本",
    "search.web":       "搜索网络",
    "search.local":     "本地搜索",
    "file.organize":    "整理文件",
    "file.transform":   "文件转换",
    "general.chat":     "通用对话",
}


# ─── 关键词 → 能力映射 ───
# 第一版用关键词匹配。V0.3 替换为 AI 分类。
# 注意：一个关键词可以映射到多个能力，Router 会选出所有匹配的 Provider。
KEYWORD_TO_CAPABILITY: dict[str, list[str]] = {
    # coding
    "写代码":      ["code.generate"],
    "写一个":      ["code.generate"],
    "实现":        ["code.generate"],
    "开发":        ["code.generate"],
    "重构":        ["code.refactor"],
    "调试":        ["code.debug"],
    "bug":         ["code.debug"],
    "函数":        ["code.generate"],
    "脚本":        ["code.generate"],
    "python":      ["code.generate"],
    "javascript":  ["code.generate"],
    "java":        ["code.generate"],
    "html":        ["code.generate"],
    "css":         ["code.generate"],
    "sql":         ["code.generate"],
    "code":        ["code.generate"],
    "function":    ["code.generate"],
    "refactor":    ["code.refactor"],
    "deploy":      ["code.generate"],
    "部署":        ["code.generate"],
    "review":      ["code.review"],

    # analysis
    "总结":        ["text.summarize"],
    "分析":        ["text.analyze"],
    "摘要":        ["text.summarize"],
    "提取":        ["text.analyze"],
    "pdf":         ["text.summarize", "text.analyze"],
    "文档":        ["text.summarize", "text.analyze"],
    "报告":        ["text.analyze"],
    "summarize":   ["text.summarize"],
    "analyze":     ["text.analyze"],

    # search
    "搜索":        ["search.web"],
    "搜一下":      ["search.web"],
    "查一下":      ["search.web"],
    "查一查":      ["search.web"],
    "查找":        ["search.web"],
    "找一下":      ["search.web"],
    "search":      ["search.web"],
    "look up":     ["search.web"],

    # file_ops
    "整理":        ["file.organize"],
    "移动":        ["file.organize"],
    "重命名":      ["file.organize"],
    "压缩":        ["file.transform"],
    "清理":        ["file.organize"],
    "文件":        ["file.organize"],
    "organize":    ["file.organize"],
    "clean":       ["file.organize"],

    # general
    "翻译":        ["text.translate"],
    "写邮件":      ["text.generate"],
    "起名字":      ["text.generate"],
    "建议":        ["general.chat"],
    "你好":        ["general.chat"],
    "hello":       ["general.chat"],
    "hi":          ["general.chat"],
    "help":        ["general.chat"],
    "问":          ["general.chat"],
}


def classify(task: str) -> list[str]:
    """通过关键词匹配，返回任务需要的所有能力标签。

    Args:
        task: 用户的任务描述

    Returns:
        能力标签列表，如 ["code.generate"]。无匹配时返回 ["general.chat"]。
    """
    task_lower = task.lower()
    caps: set[str] = set()

    for keyword, capabilities in KEYWORD_TO_CAPABILITY.items():
        if keyword in task_lower:
            caps.update(capabilities)

    if not caps:
        return ["general.chat"]

    return list(caps)
