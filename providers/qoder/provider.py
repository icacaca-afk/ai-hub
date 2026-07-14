# AI Hub — QODER Provider（使用 CLIBridge）
#
# 通信方式：CLI (subprocess)
# Bridge: CLIBridge
# Runtime: Qoder CN CLI (qoderclicn)
# 前提：已安装 qoderclicn 并登录（Browser Login）。
#
# Print 模式：qoderclicn -p "<prompt>"  （非交互，单次执行，输出结果到 stdout）
# 文档：https://help.aliyun.com/zh/lingma/qodercli-cn/product-overview/what-is-qoder-cli-cn
#
# ADR: docs/adr/0003-qoder-cli-integration.md

from __future__ import annotations

from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge
from core.health import HealthReport


class QoderProvider(Provider):
    """QODER Provider，使用 CLIBridge。

    Runtime: Qoder CN CLI v1.0.14+
    命令格式: qoderclicn -p "{task}"
    认证方式: Browser Login（首次使用需浏览器登录，之后 token 缓存）
    """

    metadata = ProviderMetadata(
        name="qoder",
        display_name="QODER",
        description="阿里 Agentic 编程平台 (Qoder CN CLI)",
        version="1.0.14",
        capabilities=[
            "code.generate",
            "code.debug",
            "code.refactor",
            "code.review",
        ],
        priority=100,
        fallback=["gemini_cli", "demo"],
        quota_type="daily",
        quota_total=80,
        quota_auto_detect=False,
        health_type="cli",
    )

    # 关键：复用 CLIBridge 已有的 command_template + env 参数，零修改 core/bridge.py
    # qoderclicn -p "{task}" 是 Print 模式（非交互），输出结果到 stdout
    bridge = CLIBridge(
        command="qoderclicn",
        command_template='qoderclicn -p "{task}"',
        version_command="qoderclicn --version",
        timeout=300,
    )

    _quota_remaining: int = 80

    def health(self) -> HealthReport:
        """CLI 是否安装。

        检查项：qoderclicn 命令是否存在、版本号是否可获取。
        """
        import time
        start = time.time()

        try:
            available = self.bridge.check_available()
            elapsed = int((time.time() - start) * 1000)

            if available:
                return HealthReport.healthy(
                    self.name,
                    latency_ms=elapsed,
                    authenticated=None,  # QODER 认证需额外检查
                    quota_ok=True,
                    message="QODER CLI ready",
                )
            else:
                return HealthReport(
                    provider=self.name,
                    status=HealthReport.DEGRADED,
                    authenticated=False,
                    quota_ok=True,
                    latency_ms=elapsed,
                    message="QODER CLI not installed or not found in PATH",
                )

        except Exception as e:
            return HealthReport.unavailable(
                self.name,
                message=f"QODER health check failed: {e}",
                latency_ms=int((time.time() - start) * 1000),
            )

    def authenticated(self) -> bool:
        """是否已登录。

        qoderclicn 没有 `auth status` 非交互命令。
        用 `-p "ping"` 能返回结果即视为已认证。
        """
        if not self.health():
            return False
        try:
            from core.task import Task
            from core.bridge import BridgeResult
            import subprocess, os
            r = subprocess.run(
                'qoderclicn -p "ping"',
                shell=True, capture_output=True, text=True,
                timeout=30, encoding="utf-8", errors="replace",
            )
            return r.returncode == 0 and len(r.stdout.strip()) > 0
        except Exception:
            return False

    def quota_left(self) -> int:
        return self._quota_remaining
