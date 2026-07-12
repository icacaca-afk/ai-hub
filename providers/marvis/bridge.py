"""Marvis UIA Bridge — 通过 Windows UIA 操控 Marvis 桌面应用。

继承 Bridge 基类，不修改 core/bridge.py。
使用 uiautomation 库直接读写 UI 元素，避免坐标操作。
"""
from __future__ import annotations

import time
import re
from typing import Optional

from core.bridge import Bridge, BridgeResult
from core.task import Task


class MarvisBridge(Bridge):
    """通过 Windows UI Automation 与 Marvis 桌面 AI 交互。

    Marvis 通常运行在系统托盘或独立窗口中。
    Bridge 查找窗口、定位输入框/发送按钮/输出区域，
    输入任务内容，等待 AI 响应，提取输出文本。

    API Stability: Experimental (V0.4)
    """

    def __init__(
        self,
        app_name: str = "Marvis",
        timeout: int = 300,
        poll_interval: float = 1.0,
        max_idle_polls: int = 5,
    ):
        self.app_name = app_name
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_idle_polls = max_idle_polls  # 连续 N 次输出不变 = 完成

    def _import_uia(self):
        try:
            import uiautomation as auto
            return auto
        except ImportError:
            return None

    def _find_window(self, auto):
        """查找 Marvis 主窗口。"""
        # 先精确匹配
        w = auto.WindowControl(Name=self.app_name, searchDepth=1)
        if w.Exists(0):
            return w

        # 模糊匹配（含 "Marvis" 子串）
        for w in auto.GetRootControl().GetChildren():
            if self.app_name.lower() in (w.Name or "").lower():
                return w

        return None

    def _find_input_control(self, window, auto):
        """在窗口中查找文本输入框。

        策略：查找 EditControl，选可聚焦的。
        """
        edits = []
        def collect_edits(ctrl, depth=0):
            if depth > 15:
                return
            if ctrl.ControlTypeName == "EditControl" and ctrl.IsEnabled:
                edits.append(ctrl)
            try:
                for child in ctrl.GetChildren():
                    collect_edits(child, depth + 1)
            except Exception:
                pass

        collect_edits(window)
        if not edits:
            return None
        # 选最大的 EditControl（主输入框通常最大）
        return max(edits, key=lambda e: (e.BoundingRectangle.width() * e.BoundingRectangle.height()))

    def _find_send_button(self, window, auto):
        """查找发送按钮。"""
        buttons = []
        def collect_buttons(ctrl, depth=0):
            if depth > 15:
                return
            if ctrl.ControlTypeName == "ButtonControl" and ctrl.IsEnabled:
                name = (ctrl.Name or "").lower()
                if any(kw in name for kw in ["发送", "send", "提交", "submit", "→", "➤"]):
                    buttons.append(ctrl)
            try:
                for child in ctrl.GetChildren():
                    collect_buttons(child, depth + 1)
            except Exception:
                pass

        collect_buttons(window)
        return buttons[0] if buttons else None

    def _find_output_area(self, window, auto):
        """查找输出/对话区域。

        策略：找最大的只读 TextControl 区域。
        """
        texts = []
        def collect_texts(ctrl, depth=0):
            if depth > 15:
                return
            if ctrl.ControlTypeName == "TextControl" or ctrl.ControlTypeName == "EditControl":
                if ctrl.IsEnabled:
                    texts.append(ctrl)
            try:
                for child in ctrl.GetChildren():
                    collect_texts(child, depth + 1)
            except Exception:
                pass

        collect_texts(window)
        if not texts:
            return None
        # 选最大的（对话区域通常最大）
        return max(texts, key=lambda t: (t.BoundingRectangle.width() * t.BoundingRectangle.height()))

    def _get_text(self, control) -> str:
        """从 UIA 控件提取文本。"""
        if control is None:
            return ""
        # 尝试多种方式获取文本
        for attr in ("Name", "ValuePattern.Value", "TextPattern.DocumentRange.GetText"):
            try:
                parts = attr.split(".")
                val = control
                for p in parts:
                    if p.endswith("()"):
                        val = getattr(val, p[:-2])()
                    else:
                        val = getattr(val, p)
                if val:
                    return str(val).strip()
            except Exception:
                pass
        return ""

    def _set_text(self, control, text: str) -> bool:
        """向 UIA 控件设置文本。"""
        if control is None:
            return False
        try:
            # 方法 1: ValuePattern.SetValue
            value_pattern = control.GetPattern(control.PatternId.ValuePatternId)
            if callable(value_pattern.SetValue):
                value_pattern.SetValue(text)
                return True
        except Exception:
            pass
        try:
            # 方法 2: SendKeys 逐个字符模拟输入
            control.SetFocus()
            import uiautomation as auto
            control.SendKeys(text)
            return True
        except Exception:
            pass
        return False

    def run(self, task: Task, **kwargs) -> BridgeResult:
        auto = self._import_uia()
        if auto is None:
            return BridgeResult(
                success=False, output="",
                error="uiautomation not installed. pip install uiautomation"
            )

        timeout = kwargs.get("timeout", self.timeout)
        start = time.time()

        try:
            # 1. 找窗口
            window = self._find_window(auto)
            if window is None:
                return BridgeResult(
                    success=False, output="",
                    error=f"Window not found: {self.app_name}. Is Marvis running?"
                )

            # 2. 找输入框
            input_ctrl = self._find_input_control(window, auto)
            if input_ctrl is None:
                return BridgeResult(
                    success=False, output="",
                    error="Input control not found in Marvis window"
                )

            # 3. 找发送按钮
            send_btn = self._find_send_button(window, auto)

            # 4. 记录输出区域当前文本（用于检测变化）
            output_ctrl = self._find_output_area(window, auto)
            prev_text = self._get_text(output_ctrl) if output_ctrl else ""

            # 5. 输入任务内容
            content = task.content
            if not self._set_text(input_ctrl, content):
                # 降级：用 SendKeys 输入
                try:
                    input_ctrl.SetFocus()
                    time.sleep(0.1)
                    input_ctrl.SendKeys(content)
                except Exception as e:
                    return BridgeResult(
                        success=False, output="",
                        error=f"Failed to input text: {e}"
                    )

            # 6. 点击发送
            if send_btn:
                try:
                    send_btn.Click()
                except Exception:
                    try:
                        # 降级：按 Enter
                        input_ctrl.SendKeys("{Enter}")
                    except Exception:
                        pass
            else:
                # 没有发送按钮，尝试按 Ctrl+Enter 或 Enter
                try:
                    input_ctrl.SendKeys("{Enter}")
                except Exception:
                    pass

            # 7. 等待响应完成（轮询输出变化）
            idle_count = 0
            output_text = prev_text
            deadline = start + timeout

            while time.time() < deadline:
                time.sleep(self.poll_interval)

                current = ""
                try:
                    output_ctrl = self._find_output_area(window, auto)
                    current = self._get_text(output_ctrl) if output_ctrl else ""
                except Exception:
                    pass

                if current == output_text:
                    idle_count += 1
                    if idle_count >= self.max_idle_polls and current and len(current) > len(prev_text):
                        break
                else:
                    output_text = current
                    idle_count = 0

            # 8. 提取新增内容
            if output_text and prev_text:
                # 尝试去除旧内容，取新增部分
                new_output = output_text
                if output_text.startswith(prev_text):
                    new_output = output_text[len(prev_text):].strip()
                elif prev_text in output_text:
                    idx = output_text.rfind(prev_text)
                    new_output = output_text[idx + len(prev_text):].strip()
            else:
                new_output = output_text

            duration_ms = int((time.time() - start) * 1000)

            return BridgeResult(
                success=bool(new_output.strip()),
                output=new_output.strip() or output_text.strip(),
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return BridgeResult(
                success=False, output="",
                error=f"MarvisBridge error: {e}",
                duration_ms=duration_ms,
            )

    def check_available(self) -> bool:
        """检查 Marvis 窗口是否存在且可交互。"""
        auto = self._import_uia()
        if auto is None:
            return False
        try:
            window = self._find_window(auto)
            if window is None:
                return False
            # 检查是否有输入框
            input_ctrl = self._find_input_control(window, auto)
            return input_ctrl is not None
        except Exception:
            return False

    def check_auth(self) -> bool:
        """GUI 认证状态由应用自身管理，窗口存在即可。"""
        return self.check_available()
