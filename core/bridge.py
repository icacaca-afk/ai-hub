# AI Hub — Bridge 层
# 桥接层：封装不同通信方式（CLI / API / GUI），对 Provider 屏蔽执行细节
#
# Provider 只需要声明用哪种 Bridge，不需要自己处理 subprocess / HTTP / GUI 自动化。
# 新增通信方式只需要新增一个 Bridge 类，不改任何 Provider。
#
# 架构位置：
#   Provider（声明能力 + 选择 Bridge）
#     ↓
#   Bridge（封装通信方式）
#     ↓
#   Runtime（CLI 进程 / HTTP 请求 / GUI 操作）
#
# API 稳定性：Experimental（V0.1 阶段，接口可能调整）

from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BridgeResult:
    """Bridge 执行结果。"""

    success: bool
    output: str
    error: str | None = None
    duration_ms: int = 0
    raw: Any = None


class Bridge(ABC):
    """所有 Bridge 的基类。

    Bridge 封装了与外部 AI 平台的通信方式。
    Provider 通过 Bridge 执行任务，不需要关心底层是 CLI / API / GUI。
    """

    @abstractmethod
    def run(self, task: str, **kwargs) -> BridgeResult:
        """执行任务。

        Args:
            task: 任务描述
            **kwargs: 额外参数（命令模板、超时等）

        Returns:
            BridgeResult
        """
        ...

    @abstractmethod
    def check_available(self) -> bool:
        """检查 Bridge 是否可用（CLI 已安装 / API 可达 / GUI 可操控）。"""
        ...


class CLIBridge(Bridge):
    """CLI 桥接器。

    通过 subprocess 调用外部 CLI 工具执行任务。
    适用于：QODER、Gemini CLI、QClaw (openclaw) 等。

    使用方式：
        bridge = CLIBridge(command="gemini")
        result = bridge.run("写一个 Python 服务")
    """

    def __init__(
        self,
        command: str,
        auth_command: str | None = None,
        version_command: str | None = None,
        timeout: int = 300,
    ):
        self.command = command
        self.auth_command = auth_command or f"{command} --version"
        self.version_command = version_command or f"{command} --version"
        self.timeout = timeout

    def run(self, task: str, **kwargs) -> BridgeResult:
        cmd = kwargs.get("command_template", f'{self.command} "{{task}}"')
        timeout = kwargs.get("timeout", self.timeout)
        full_cmd = cmd.format(task=task)

        start = time.time()
        try:
            proc = subprocess.run(
                full_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            duration = int((time.time() - start) * 1000)

            if proc.returncode == 0:
                return BridgeResult(
                    success=True,
                    output=proc.stdout.strip(),
                    error=None,
                    duration_ms=duration,
                    raw=proc,
                )
            else:
                return BridgeResult(
                    success=False,
                    output=proc.stdout.strip(),
                    error=proc.stderr.strip() or f"Exit code {proc.returncode}",
                    duration_ms=duration,
                    raw=proc,
                )
        except subprocess.TimeoutExpired:
            return BridgeResult(
                success=False,
                output="",
                error=f"Timeout after {timeout}s",
                duration_ms=timeout * 1000,
            )
        except FileNotFoundError:
            return BridgeResult(
                success=False,
                output="",
                error=f"Command not found: {self.command}",
                duration_ms=0,
            )
        except Exception as e:
            return BridgeResult(
                success=False,
                output="",
                error=str(e),
                duration_ms=int((time.time() - start) * 1000),
            )

    def check_available(self) -> bool:
        try:
            proc = subprocess.run(
                self.version_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
                errors="replace",
            )
            return proc.returncode == 0
        except Exception:
            return False

    def check_auth(self) -> bool:
        try:
            proc = subprocess.run(
                self.auth_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
                errors="replace",
            )
            return proc.returncode == 0
        except Exception:
            return False


class APIBridge(Bridge):
    """API 桥接器。

    通过 HTTP 请求调用外部 API 执行任务。
    适用于：OpenAI API、Claude API、QODER API（如果有）等。

    使用方式：
        bridge = APIBridge(
            endpoint="https://api.example.com/v1/chat",
            api_key_env="EXAMPLE_API_KEY",
        )
        result = bridge.run("写一个 Python 服务")
    """

    def __init__(
        self,
        endpoint: str,
        api_key_env: str,
        method: str = "POST",
        timeout: int = 300,
        headers: dict[str, str] | None = None,
    ):
        self.endpoint = endpoint
        self.api_key_env = api_key_env
        self.method = method
        self.timeout = timeout
        self.headers = headers or {}

    def _get_api_key(self) -> str | None:
        import os
        return os.environ.get(self.api_key_env)

    def run(self, task: str, **kwargs) -> BridgeResult:
        import json
        import urllib.request

        api_key = self._get_api_key()
        if not api_key:
            return BridgeResult(
                success=False,
                output="",
                error=f"API key not set in env: {self.api_key_env}",
            )

        body = json.dumps({
            "task": task,
            **kwargs.get("extra_body", {}),
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            **self.headers,
        }

        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers=headers,
            method=self.method,
        )

        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                output = resp.read().decode("utf-8")
                duration = int((time.time() - start) * 1000)
                return BridgeResult(
                    success=True,
                    output=output,
                    duration_ms=duration,
                )
        except urllib.error.HTTPError as e:
            return BridgeResult(
                success=False,
                output="",
                error=f"HTTP {e.code}: {e.reason}",
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return BridgeResult(
                success=False,
                output="",
                error=str(e),
                duration_ms=int((time.time() - start) * 1000),
            )

    def check_available(self) -> bool:
        api_key = self._get_api_key()
        return api_key is not None

    def check_auth(self) -> bool:
        return self.check_available()


class FakeBridge(Bridge):
    """Fake 桥接器。

    不调用任何外部服务，永远返回预设结果。
    用于：
    - 骨架验证
    - 单元测试
    - Provider 开发调试

    使用方式：
        bridge = FakeBridge(response="Hello AI Hub!")
        result = bridge.run("任何任务")
    """

    def __init__(
        self,
        response: str = "Hello AI Hub!",
        available: bool = True,
        delay_ms: int = 0,
    ):
        self.response = response
        self._available = available
        self.delay_ms = delay_ms

    def run(self, task: str, **kwargs) -> BridgeResult:
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000)
        return BridgeResult(
            success=True,
            output=f"{self.response}\n\nYou said: {task}",
            duration_ms=self.delay_ms,
        )

    def check_available(self) -> bool:
        return self._available

    def check_auth(self) -> bool:
        return self._available
