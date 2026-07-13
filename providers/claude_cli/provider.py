# AI Hub — Claude CLI Provider（真实接入）
#
# 通信方式：CLI (subprocess)
# Bridge: CLIBridge
# Runtime: Claude Code CLI
#
# 前提条件：
#   1. 安装 Claude Code CLI（https://docs.claude.com/claude-code）
#   2. 设置 ANTHROPIC_API_KEY 环境变量，或提前运行 `claude login` 完成 OAuth 登录
#
# Print 模式（非交互，单次执行，输出结果到 stdout）：
#   claude -p "{task}"
#
# ADR: docs/adr/0007-claude-cli-integration.md

from __future__ import annotations

import os

from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge


# 从环境变量读取配置，避免硬编码
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


class ClaudeCLIProvider(Provider):
    """Claude CLI Provider，使用 CLIBridge 调用 Claude Code CLI。

    支持的能力：代码生成、调试、重构、代码审查、文本摘要、翻译、通用对话。
    认证方式：ANTHROPIC_API_KEY 环境变量，或已完成的 `claude login` OAuth 登录。
    """

    metadata = ProviderMetadata(
        name="claude_cli",
        display_name="Claude CLI",
        description="Anthropic Claude Code 命令行工具（claude -p）",
        version="0.1.0",
        capabilities=[
            "code.generate",
            "code.debug",
            "code.refactor",
            "code.review",
            "text.summarize",
            "text.translate",
            "general.chat",
        ],
        priority=85,
        fallback=["gemini_cli", "demo"],
        quota_type="unknown",
        quota_total=-1,
    )

    bridge = CLIBridge(
        command="claude",
        version_command="claude --version",
        timeout=300,
        command_template='claude -p "{task}"',
        env=({"ANTHROPIC_API_KEY": ANTHROPIC_API_KEY} if ANTHROPIC_API_KEY else {}),
    )

    def health(self) -> bool:
        """检查 Claude CLI 是否已安装。"""
        return self.bridge.check_available()

    def authenticated(self) -> bool:
        """检查是否已认证。

        Claude CLI 支持两种认证方式：ANTHROPIC_API_KEY 环境变量，
        或提前完成的 `claude login` OAuth 登录（token 由 CLI 自行缓存）。
        没有独立的非交互 `auth status` 命令，所以：
        - 如果设置了 ANTHROPIC_API_KEY，直接视为已认证。
        - 否则退化为检查 CLI 是否可用（假设用户已通过 `claude login` 登录）。
        """
        if ANTHROPIC_API_KEY:
            return True
        return self.health()

    def quota_left(self) -> int:
        """Claude CLI 没有可查询的免费额度接口，返回 -1（未知/不限制单次调用）。"""
        return -1
