"""AI Hub Provider for the locally installed Trae CLI."""

from __future__ import annotations

import time

from core.bridge import CLIBridge
from core.health import HealthReport
from core.provider import Provider, ProviderMetadata


class TraeCLIProvider(Provider):
    """Trae Work CLI adapter using its non-interactive print mode.

    The Provider intentionally reuses the existing Provider/Bridge boundary.
    Callers choose whether a task is read-only; the provider itself remains
    capable of ordinary Trae coding tasks.
    """

    metadata = ProviderMetadata(
        name="trae_cli",
        display_name="Trae CLI",
        description="Trae Work code agent CLI (trae-cli -p)",
        version="0.1.0",
        capabilities=[
            "code.generate",
            "code.debug",
            "code.refactor",
            "code.review",
            "text.summarize",
            "general.chat",
        ],
        priority=90,
        fallback=["claude_cli", "gemini_cli", "demo"],
        quota_type="unknown",
        quota_total=-1,
        health_type="cli",
        timeout=900,
    )

    bridge = CLIBridge(
        command="trae-cli",
        # `doctor` is a non-destructive readiness check and catches the
        # common "binary installed but no model configured" state.
        version_command="trae-cli doctor",
        auth_command="trae-cli doctor",
        timeout=900,
        command_template='trae-cli -p "{task}" --output-format text',
    )

    def health(self) -> HealthReport:
        """Report whether Trae is installed and has an effective model."""
        start = time.time()
        try:
            if not self.bridge.check_available():
                return HealthReport.unavailable(
                    self.name,
                    message=(
                        "trae-cli unavailable or not configured; run "
                        "`trae-cli doctor` for details"
                    ),
                    latency_ms=int((time.time() - start) * 1000),
                )
            elapsed = int((time.time() - start) * 1000)
            return HealthReport.healthy(
                self.name,
                latency_ms=elapsed,
                authenticated=None,
                quota_ok=True,
                message="Trae CLI ready; authentication and model are CLI-managed",
            )
        except Exception as error:
            return HealthReport.unavailable(
                self.name,
                message=f"Trae CLI health check failed: {error}",
                latency_ms=int((time.time() - start) * 1000),
            )

    def authenticated(self) -> bool:
        """Use the CLI version check as a non-invasive readiness signal."""
        return self.bridge.check_available()

    def quota_left(self) -> int:
        """Trae CLI quota is managed outside AI Hub."""
        return -1
