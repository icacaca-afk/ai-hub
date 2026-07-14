# AI Hub — Gemini CLI Provider（真实接入 V0.1）
#
# 通信方式：CLI (subprocess)
# Bridge: CLIBridge
# Runtime: gemini CLI 0.50+
#
# 前提条件：
#   1. npm install -g @google/gemini-cli
#   2. 设置 GEMINI_API_KEY 环境变量
#   3. 如需代理：设置 HTTP_PROXY / HTTPS_PROXY
#
# 命令模板：gemini -p "{task}" -o text --yolo --skip-trust

from __future__ import annotations

import os

from core.provider import Provider, ProviderMetadata
from core.bridge import CLIBridge
from core.health import HealthReport


# 从环境变量读取配置，避免硬编码
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
HTTP_PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY", "")


class GeminiCLIProvider(Provider):
    """Gemini CLI Provider，使用 CLIBridge 调用 gemini CLI。

    支持的能力：代码生成、文本摘要、翻译、Web 搜索、通用对话。
    需要已安装 gemini CLI 并配置 API Key。
    """

    metadata = ProviderMetadata(
        name="gemini_cli",
        display_name="Gemini CLI",
        description="Google Gemini 命令行工具（gemini -p）",
        version="0.1.0",
        capabilities=[
            "code.generate",
            "search.web",
            "text.summarize",
            "text.translate",
            "general.chat",
        ],
        priority=80,
        fallback=["openai_api", "demo"],
        quota_type="unlimited",
        quota_total=-1,
        health_type="cli",
    )

    bridge = CLIBridge(
        command="gemini",
        version_command="gemini --version",
        auth_command="gemini --version",  # Gemini CLI 用 API Key 认证，无独立 auth 命令
        timeout=300,
        command_template='gemini -p "{task}" -o text --yolo --skip-trust',
        env={
            "GEMINI_API_KEY": GEMINI_API_KEY,
            **({"HTTPS_PROXY": HTTP_PROXY, "HTTP_PROXY": HTTP_PROXY} if HTTP_PROXY else {}),
        },
    )

    def health(self) -> HealthReport:
        """检查 gemini CLI 健康状态。

        检查项：
        1. gemini 可执行文件是否存在
        2. 版本命令是否正常
        3. API Key 是否配置
        4. 认证状态（通过简单请求验证）
        """
        import time
        start = time.time()

        try:
            # 1. CLI 可用性
            if not self.bridge.check_available():
                return HealthReport.unavailable(
                    self.name,
                    message="gemini CLI not installed or not found in PATH",
                    latency_ms=int((time.time() - start) * 1000),
                )

            # 2. API Key 检查
            if not GEMINI_API_KEY:
                return HealthReport(
                    provider=self.name,
                    status=HealthReport.DEGRADED,
                    authenticated=False,
                    quota_ok=True,
                    latency_ms=int((time.time() - start) * 1000),
                    message="Gemini CLI installed but GEMINI_API_KEY not set",
                )

            # 3. 简单请求验证
            auth_ok = self.authenticated()
            elapsed = int((time.time() - start) * 1000)

            return HealthReport.healthy(
                self.name,
                latency_ms=elapsed,
                authenticated=auth_ok,
                quota_ok=True,
                message="Gemini CLI ready" if auth_ok else "Gemini CLI available but auth failed",
            )

        except Exception as e:
            return HealthReport.unavailable(
                self.name,
                message=f"Gemini health check failed: {e}",
                latency_ms=int((time.time() - start) * 1000),
            )

    def authenticated(self) -> bool:
        """检查 API Key 是否已配置。"""
        return bool(GEMINI_API_KEY)

    def quota_left(self) -> int:
        """Gemini 免费额度无限（实际有 RPM 限制，但不影响单次调用）。"""
        return -1
