# AI Hub — Bridge 层
# 桥接层：封装不同通信方式（CLI / API / GUI / Browser），对 Provider 屏蔽执行细节
#
# Provider 只声明用哪种 Bridge，不关心底层是 subprocess / HTTP / GUI。
# 新增通信方式只需要新增一个 Bridge 类，不改任何 Provider。
#
# 架构位置：
#   Provider（声明能力 + 选择 Bridge）
#     ↓
#   Bridge（封装通信方式）
#     ↓
#   Runtime（CLI 进程 / HTTP 请求 / GUI 操作 / 浏览器控制）
#
# API Stability: Experimental（V0.1 阶段接口可能调整）

from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from core.task import Task


@dataclass
class BridgeResult:
    """Bridge 执行结果。

    由 Bridge.run() 返回，Router 负责将其转换为 Result。
    """

    success: bool
    output: str                           # 纯文本输出
    error: str | None = None
    duration_ms: int = 0
    artifacts: list[str] = field(default_factory=list)  # 产物文件路径
    raw: Any = None


class Bridge(ABC):
    """所有 Bridge 的基类。

    Bridge 封装了与外部 Runtime 的通信方式。
    Provider 通过 select_bridge(task) 返回 Bridge 实例，
    Router 调用 bridge.run(task) 执行任务。

    API Stability: Experimental
    """

    @abstractmethod
    def run(self, task: Task, **kwargs) -> BridgeResult:
        """执行任务。

        Args:
            task: Task 对象（包含 content、capabilities、context、artifacts）
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

    支持自定义命令模板和环境变量注入，适配不同 CLI 的调用方式。

    API Stability: Experimental
    """

    def __init__(
        self,
        command: str,
        auth_command: str | None = None,
        version_command: str | None = None,
        timeout: int = 300,
        command_template: str | None = None,
        env: dict[str, str] | None = None,
    ):
        self.command = command
        self.auth_command = auth_command or f"{command} --version"
        self.version_command = version_command or f"{command} --version"
        self.timeout = timeout
        # 自定义命令模板，如 'gemini -p "{task}" -o text --yolo --skip-trust'
        # {task} 会被替换为 task.content
        self.command_template = command_template or f'{command} "{{task}}"'
        # 额外环境变量（会与 os.environ 合并）
        self.env = env or {}

    def _build_env(self) -> dict[str, str]:
        """合并 os.environ 和 self.env。"""
        import os
        merged = os.environ.copy()
        merged.update(self.env)
        return merged

    def run(self, task: Task, **kwargs) -> BridgeResult:
        cmd_template = kwargs.get("command_template", self.command_template)
        timeout = kwargs.get("timeout", self.timeout)
        # 转义双引号，防止命令注入
        safe_content = task.content.replace('"', '\\"')
        full_cmd = cmd_template.format(task=safe_content)

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
                env=self._build_env(),
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
                env=self._build_env(),
            )
            return proc.returncode == 0
        except Exception:
            return False

    def check_auth(self) -> bool:
        # 对于用 API Key 认证的 CLI，检查环境变量是否存在
        if self.env:
            import os
            # 如果 env 中有 API key 类的变量且值不为空，认为已认证
            api_keys = [v for k, v in self.env.items() if "KEY" in k.upper() or "TOKEN" in k.upper()]
            if api_keys:
                return all(v for v in api_keys)
        # 否则用 auth_command 检查
        try:
            proc = subprocess.run(
                self.auth_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
                errors="replace",
                env=self._build_env(),
            )
            return proc.returncode == 0
        except Exception:
            return False


class APIBridge(Bridge):
    """API 桥接器。

    通过 HTTP 请求调用外部 API 执行任务。
    适用于：OpenAI API、OpenAI 兼容 API、Claude API 等。

    参考 CLIBridge 风格设计：
    - body_template: 请求体模板（对应 command_template），支持 {task} / {model} 占位符
    - response_extractor: 响应提取路径（如 "choices[0].message.content"）
    - health_endpoint: 健康检查端点（对应 version_command）

    API Stability: Experimental
    """

    def __init__(
        self,
        endpoint: str,
        api_key_env: str,
        method: str = "POST",
        timeout: int = 300,
        headers: dict[str, str] | None = None,
        body_template: dict | None = None,
        response_extractor: str | None = None,
        health_endpoint: str | None = None,
    ):
        self.endpoint = endpoint
        self.api_key_env = api_key_env
        self.method = method
        self.timeout = timeout
        self.headers = headers or {}
        self.body_template = body_template or {
            "task": "{task}",
            "capabilities": [],
        }
        self.response_extractor = response_extractor
        self.health_endpoint = health_endpoint

    def _get_api_key(self) -> str | None:
        import os
        return os.environ.get(self.api_key_env)

    def _build_body(self, task: Task, **kwargs) -> dict:
        import copy
        template = kwargs.get("body_template", self.body_template)
        return self._apply_template(template, task, **kwargs)

    def _apply_template(self, template: dict, task: Task, **kwargs) -> dict:
        import copy

        def _replace(val):
            if isinstance(val, str):
                return val.format(
                    task=task.content,
                    model=kwargs.get("model", ""),
                )
            elif isinstance(val, dict):
                return {k: _replace(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [_replace(item) for item in val]
            else:
                return val

        return _replace(copy.deepcopy(template))

    def _extract_output(self, response_text: str) -> str:
        import json

        if not self.response_extractor:
            return response_text

        try:
            data = json.loads(response_text)
        except (json.JSONDecodeError, TypeError):
            return response_text

        path = self.response_extractor
        current = data
        try:
            import re
            tokens = re.findall(r'[^.\[\]]+', path)
            for token in tokens:
                if isinstance(current, list):
                    try:
                        idx = int(token)
                        current = current[idx]
                    except (ValueError, IndexError):
                        return response_text
                elif isinstance(current, dict):
                    if token in current:
                        current = current[token]
                    else:
                        return response_text
                else:
                    return response_text
            return str(current) if current is not None else ""
        except Exception:
            return response_text

    def _build_headers(self, api_key: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            **self.headers,
        }

    def run(self, task: Task, **kwargs) -> BridgeResult:
        import json
        import urllib.request
        import urllib.error

        api_key = self._get_api_key()
        if not api_key:
            return BridgeResult(
                success=False,
                output="",
                error=f"API key not set in env: {self.api_key_env}",
            )

        body_dict = self._build_body(task, **kwargs)
        extra_body = kwargs.get("extra_body", {})
        if extra_body:
            body_dict.update(extra_body)
        body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")

        headers = self._build_headers(api_key)
        endpoint = kwargs.get("endpoint", self.endpoint)

        req = urllib.request.Request(
            endpoint,
            data=body,
            headers=headers,
            method=self.method,
        )

        start = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw_output = resp.read().decode("utf-8", errors="replace")
                duration = int((time.time() - start) * 1000)
                output = self._extract_output(raw_output)
                return BridgeResult(
                    success=True,
                    output=output,
                    duration_ms=duration,
                    raw=raw_output,
                )
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            return BridgeResult(
                success=False,
                output="",
                error=f"HTTP {e.code}: {e.reason}\n{error_body}",
                duration_ms=int((time.time() - start) * 1000),
                raw=error_body,
            )
        except urllib.error.URLError as e:
            return BridgeResult(
                success=False,
                output="",
                error=f"URL Error: {e.reason}",
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
        if not api_key:
            return False

        if self.health_endpoint:
            import urllib.request
            import urllib.error

            try:
                headers = self._build_headers(api_key)
                if self.health_endpoint.startswith("http"):
                    url = self.health_endpoint
                else:
                    base = self.endpoint.rsplit("/", 2)[0] if "/v1/" in self.endpoint else self.endpoint.rsplit("/", 1)[0]
                    url = base + self.health_endpoint

                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return 200 <= resp.status < 300
            except Exception:
                return False

        return True

    def check_auth(self) -> bool:
        return self.check_available()


class FakeBridge(Bridge):
    """Fake 桥接器。

    不调用任何外部服务，返回预设结果。
    用于：骨架验证、单元测试、Provider 开发调试。

    支持 timeout / retry / artifacts 模拟，用于 Contract Test。

    API Stability: Stable
    """

    def __init__(
        self,
        response: str = "Hello AI Hub!",
        available: bool = True,
        delay_ms: int = 0,
        timeout_ms: int = 0,
        fail_times: int = 0,
        artifacts: list[str] | None = None,
    ):
        self.response = response
        self._available = available
        self.delay_ms = delay_ms
        self.timeout_ms = timeout_ms
        self.fail_times = fail_times
        self.output_artifacts = artifacts or []
        self._call_count = 0

    def run(self, task: Task, **kwargs) -> BridgeResult:
        self._call_count += 1

        # 模拟超时
        timeout = kwargs.get("timeout", self.timeout_ms)
        if timeout and timeout > 0:
            if self.delay_ms > 0:
                time.sleep(self.delay_ms / 1000)
            return BridgeResult(
                success=False,
                output="",
                error=f"Timeout after {timeout}s",
                duration_ms=timeout * 1000,
            )

        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000)

        # 模拟前 N 次失败（用于 retry 测试）
        if self._call_count <= self.fail_times:
            return BridgeResult(
                success=False,
                output="",
                error=f"Simulated failure (attempt {self._call_count}/{self.fail_times})",
                duration_ms=self.delay_ms,
            )

        return BridgeResult(
            success=True,
            output=f"{self.response}\n\nYou said: {task.content}",
            duration_ms=self.delay_ms,
            artifacts=list(self.output_artifacts) if self.output_artifacts else [],
        )

    def check_available(self) -> bool:
        return self._available

    def check_auth(self) -> bool:
        return self._available

    @property
    def call_count(self) -> int:
        """已调用次数（用于 retry 测试断言）。"""
        return self._call_count

    def reset(self) -> None:
        """重置调用计数（用于测试隔离）。"""
        self._call_count = 0


class GUIBridge(Bridge):
    """GUI 桥接器。

    通过 pyautogui 操控桌面 GUI。
    适用于：Marvis、桌面应用等没有 CLI/API 的平台。

    支持的 action 类型：
        - move:    {"action": "move", "x": 100, "y": 200}
        - click:   {"action": "click", "x": 100, "y": 200, "button": "left"}
        - type:    {"action": "type", "text": "hello world"}
        - press:   {"action": "press", "key": "Enter"}
        - screenshot: {"action": "screenshot", "name": "result"}
        - wait:    {"action": "wait", "seconds": 2}
        - scroll:  {"action": "scroll", "dy": 300}

    Actions 来源（优先级）：
        1. kwargs["actions"]
        2. task.context["actions"]
        3. 如果 task.content 是 JSON 且能解析为 action list，则使用

    API Stability: Experimental
    """

    def __init__(
        self,
        app_name: str = "",
        timeout: int = 300,
        screenshot_dir: str = "/tmp/ai_hub_gui",
    ):
        self.app_name = app_name
        self.timeout = timeout
        self.screenshot_dir = screenshot_dir

    def _import_pyautogui(self):
        try:
            import pyautogui
            return pyautogui
        except ImportError:
            return None

    def _get_actions(self, task: Task, **kwargs) -> list[dict]:
        actions = kwargs.get("actions")
        if actions:
            return actions
        actions = task.context.get("actions")
        if actions:
            return actions
        import json
        try:
            parsed = json.loads(task.content)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    def run(self, task: Task, **kwargs) -> BridgeResult:
        import os
        import json

        pyautogui = self._import_pyautogui()
        if pyautogui is None:
            return BridgeResult(
                success=False,
                output="",
                error="pyautogui is not installed. Install with: pip install pyautogui",
            )

        actions = self._get_actions(task, **kwargs)
        if not actions:
            return BridgeResult(
                success=False,
                output="",
                error="No actions provided. Pass actions via kwargs, task.context, or JSON in task.content.",
            )

        os.makedirs(self.screenshot_dir, exist_ok=True)
        artifacts: list[str] = []
        output_parts: list[str] = []
        start = time.time()

        try:
            for i, action in enumerate(actions):
                act_type = action.get("action", "")

                if act_type == "move":
                    x = action.get("x", 0)
                    y = action.get("y", 0)
                    duration = action.get("duration", 0.0)
                    pyautogui.moveTo(x, y, duration=duration)
                    output_parts.append(f"Moved to ({x}, {y})")

                elif act_type == "click":
                    x = action.get("x")
                    y = action.get("y")
                    button = action.get("button", "left")
                    clicks = action.get("clicks", 1)
                    if x is not None and y is not None:
                        pyautogui.click(x, y, button=button, clicks=clicks)
                        output_parts.append(f"Clicked ({x}, {y}) [{button}]")
                    else:
                        pyautogui.click(button=button, clicks=clicks)
                        output_parts.append(f"Clicked [{button}]")

                elif act_type == "type":
                    text = action.get("text", "")
                    interval = action.get("interval", 0.0)
                    pyautogui.typewrite(text, interval=interval) if isinstance(text, str) else None
                    output_parts.append(f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}")

                elif act_type == "press":
                    key = action.get("key", "")
                    if key:
                        pyautogui.press(key)
                        output_parts.append(f"Pressed: {key}")

                elif act_type == "screenshot":
                    name = action.get("name", f"screenshot_{i}")
                    path = os.path.join(self.screenshot_dir, f"{name}.png")
                    pyautogui.screenshot(path)
                    artifacts.append(path)
                    output_parts.append(f"Screenshot saved: {path}")

                elif act_type == "wait":
                    seconds = action.get("seconds", 1)
                    time.sleep(seconds)
                    output_parts.append(f"Waited {seconds}s")

                elif act_type == "scroll":
                    dy = action.get("dy", 300)
                    x = action.get("x")
                    y = action.get("y")
                    if x is not None and y is not None:
                        pyautogui.scroll(dy, x=x, y=y)
                    else:
                        pyautogui.scroll(dy)
                    output_parts.append(f"Scrolled {dy}")

                else:
                    output_parts.append(f"Unknown action: {act_type}")

            duration_ms = int((time.time() - start) * 1000)
            return BridgeResult(
                success=True,
                output="\n".join(output_parts),
                duration_ms=duration_ms,
                artifacts=artifacts,
            )

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return BridgeResult(
                success=False,
                output="\n".join(output_parts),
                error=f"GUIBridge error: {e}",
                duration_ms=duration_ms,
                artifacts=artifacts,
            )

    def check_available(self) -> bool:
        pyautogui = self._import_pyautogui()
        if pyautogui is None:
            return False
        try:
            size = pyautogui.size()
            return size.width > 0 and size.height > 0
        except Exception:
            return False

    def check_auth(self) -> bool:
        return self.check_available()


class BrowserBridge(Bridge):
    """Browser 桥接器。

    通过 Playwright 操控浏览器，适用于 Web AI 服务。
    如：Claude Web、ChatGPT Web 等没有公开 API 的平台。

    支持的 action 类型：
        - goto:       {"action": "goto", "url": "https://example.com"}
        - wait:      {"action": "wait", "selector": "#content", "timeout": 5000}
        - input:     {"action": "input", "selector": "#search", "text": "hello"}
        - click:     {"action": "click", "selector": "#submit"}
        - screenshot: {"action": "screenshot", "name": "result"}
        - extract:   {"action": "extract", "selector": "#output"}
        - scroll:    {"action": "scroll", "dy": 500}
        - evaluate:  {"action": "evaluate", "script": "document.title"}
        - close:     {"action": "close"}

    Actions 来源（优先级）：
        1. kwargs["actions"]
        2. task.context["actions"]
        3. 如果 task.content 是 URL（以 http 开头），自动构造 goto + screenshot
        4. 如果 task.content 是 JSON 且能解析为 action list，则使用

    API Stability: Experimental
    """

    def __init__(
        self,
        url: str = "",
        timeout: int = 300,
        headless: bool = True,
        browser_type: str = "chromium",
        screenshot_dir: str = "/tmp/ai_hub_browser",
    ):
        self.url = url
        self.timeout = timeout
        self.headless = headless
        self.browser_type = browser_type
        self.screenshot_dir = screenshot_dir

    def _import_playwright(self):
        try:
            from playwright.sync_api import sync_playwright
            return sync_playwright
        except ImportError:
            return None

    def _get_actions(self, task: Task, **kwargs) -> list[dict]:
        actions = kwargs.get("actions")
        if actions:
            return actions
        actions = task.context.get("actions")
        if actions:
            return actions
        import json
        try:
            parsed = json.loads(task.content)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        # If content looks like a URL, auto-generate goto + screenshot
        content = task.content.strip()
        if content.startswith("http://") or content.startswith("https://"):
            return [
                {"action": "goto", "url": content},
                {"action": "screenshot", "name": "page"},
            ]
        return []

    def run(self, task: Task, **kwargs) -> BridgeResult:
        import os

        sync_playwright = self._import_playwright()
        if sync_playwright is None:
            return BridgeResult(
                success=False,
                output="",
                error="playwright is not installed. Install with: pip install playwright && playwright install",
            )

        actions = self._get_actions(task, **kwargs)
        if not actions:
            return BridgeResult(
                success=False,
                output="",
                error="No actions provided. Pass actions via kwargs, task.context, JSON in task.content, or a URL.",
            )

        os.makedirs(self.screenshot_dir, exist_ok=True)
        artifacts: list[str] = []
        output_parts: list[str] = []
        start = time.time()

        browser_type = kwargs.get("browser_type", self.browser_type)
        headless = kwargs.get("headless", self.headless)

        try:
            with sync_playwright() as p:
                browser_launcher = getattr(p, browser_type, None)
                if browser_launcher is None:
                    return BridgeResult(
                        success=False,
                        output="",
                        error=f"Unknown browser type: {browser_type}. Supported: chromium, firefox, webkit",
                        duration_ms=int((time.time() - start) * 1000),
                    )

                browser = browser_launcher.launch(headless=headless)
                context = browser.new_context()
                page = context.new_page()

                if self.url and not any(a.get("action") == "goto" for a in actions):
                    page.goto(self.url, timeout=self.timeout * 1000)

                for i, action in enumerate(actions):
                    act_type = action.get("action", "")

                    if act_type == "goto":
                        url = action.get("url", "")
                        page.goto(url, timeout=action.get("timeout", self.timeout * 1000))
                        output_parts.append(f"Navigated to: {url}")

                    elif act_type == "wait":
                        selector = action.get("selector")
                        wait_timeout = action.get("timeout", 30000)
                        if selector:
                            page.wait_for_selector(selector, timeout=wait_timeout)
                            output_parts.append(f"Waited for: {selector}")
                        else:
                            page.wait_for_load_state("networkidle", timeout=wait_timeout)
                            output_parts.append("Waited for network idle")

                    elif act_type == "input":
                        selector = action.get("selector", "")
                        text = action.get("text", "")
                        page.fill(selector, text)
                        output_parts.append(f"Input into {selector}: {text[:50]}")

                    elif act_type == "click":
                        selector = action.get("selector", "")
                        page.click(selector)
                        output_parts.append(f"Clicked: {selector}")

                    elif act_type == "screenshot":
                        name = action.get("name", f"screenshot_{i}")
                        path = os.path.join(self.screenshot_dir, f"{name}.png")
                        page.screenshot(path=path)
                        artifacts.append(path)
                        output_parts.append(f"Screenshot: {path}")

                    elif act_type == "extract":
                        selector = action.get("selector", "")
                        attr = action.get("attr", "textContent")
                        extracted = page.get_attribute(selector, attr) if attr != "textContent" else page.text_content(selector)
                        output_parts.append(f"Extracted [{selector}]: {extracted}")

                    elif act_type == "scroll":
                        dy = action.get("dy", 500)
                        page.mouse.wheel(0, dy)
                        output_parts.append(f"Scrolled down {dy}px")

                    elif act_type == "evaluate":
                        script = action.get("script", "")
                        result = page.evaluate(script)
                        output_parts.append(f"Evaluate result: {result}")

                    elif act_type == "close":
                        context.close()
                        browser.close()
                        output_parts.append("Browser closed")

                    else:
                        output_parts.append(f"Unknown action: {act_type}")

                if not any(a.get("action") == "close" for a in actions):
                    context.close()
                    browser.close()

            duration_ms = int((time.time() - start) * 1000)
            return BridgeResult(
                success=True,
                output="\n".join(output_parts),
                duration_ms=duration_ms,
                artifacts=artifacts,
            )

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return BridgeResult(
                success=False,
                output="\n".join(output_parts),
                error=f"BrowserBridge error: {e}",
                duration_ms=duration_ms,
                artifacts=artifacts,
            )

    def check_available(self) -> bool:
        sync_playwright = self._import_playwright()
        if sync_playwright is None:
            return False
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            return True
        except Exception:
            return False

    def check_auth(self) -> bool:
        return self.check_available()
