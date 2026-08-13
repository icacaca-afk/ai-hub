# AI Hub — Claude CLI Provider
#
# Communication: CLI (subprocess)
# Bridge: CLIBridge
# Runtime: Claude Code CLI
#
# Prerequisites:
#   1. Install Claude Code CLI (https://docs.claude.com/claude-code)
#   2. Set ANTHROPIC_API_KEY environment variable, or run `claude login`
#      to complete OAuth login in advance.
#
# Print mode (non-interactive, single execution, output to stdout):
#   claude -p "{task}"
#
# ADR: docs/adr/0036-claude-cli-integration.md

from __future__ import annotations

import os
import time

from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge
from core.health import HealthReport


class ClaudeCLIProvider(Provider):
    """Claude CLI Provider using CLIBridge to invoke Claude Code CLI.

    Supported capabilities: code generation, debugging, refactoring, code
    review, text summarization, translation, and general chat.
    Authentication: ANTHROPIC_API_KEY environment variable, or a completed
    `claude login` OAuth session (token cached by the CLI itself).
    """

    metadata = ProviderMetadata(
        name="claude_cli",
        display_name="Claude CLI",
        description="Anthropic Claude Code CLI (claude -p)",
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
        health_type="cli",
    )

    bridge = CLIBridge(
        command="claude",
        version_command="claude --version",
        timeout=300,
        command_template='claude -p "{task}"',
    )

    def health(self) -> HealthReport:
        """Check Claude CLI health status.

        Returns healthy if the claude executable is found in PATH,
        unavailable otherwise.
        """
        start = time.time()

        try:
            if not self.bridge.check_available():
                return HealthReport.unavailable(
                    self.name,
                    message="claude CLI not installed or not found in PATH",
                    latency_ms=int((time.time() - start) * 1000),
                )

            elapsed = int((time.time() - start) * 1000)
            return HealthReport.healthy(
                self.name,
                latency_ms=elapsed,
                authenticated=self.authenticated(),
                quota_ok=True,
                message="Claude CLI ready",
            )

        except Exception as e:
            return HealthReport.unavailable(
                self.name,
                message=f"Claude CLI health check failed: {e}",
                latency_ms=int((time.time() - start) * 1000),
            )

    def authenticated(self) -> bool:
        """Check whether the provider is authenticated.

        Claude CLI supports two authentication modes:
        - ANTHROPIC_API_KEY environment variable
        - A prior `claude login` OAuth session (token cached by the CLI)

        The API key is read at call time so that changes take effect
        without a process restart.
        If ANTHROPIC_API_KEY is set, it is considered authenticated.
        Otherwise, authentication is assumed if the CLI is available
        (the user is expected to have run `claude login`).
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key:
            return True
        return self.bridge.check_available()

    def quota_left(self) -> int:
        """Claude CLI has no queryable quota interface; return -1 (unlimited)."""
        return -1
