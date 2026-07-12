"""Marvis Win32 Bridge — 通过键盘模拟 + 剪贴板操控桌面应用。

继承 Bridge 基类，不修改 core/bridge.py。
Marvis 是 Qt 应用，不暴露 UIA 内部控件树 → 用 Win32 键盘事件。
此策略通用：Electron / Qt / 原生 Win32 均适用。

API Stability: Experimental (V0.4)
"""
from __future__ import annotations

import ctypes
import time
import re
from typing import Optional

from core.bridge import Bridge, BridgeResult
from core.task import Task

# ── Win32 constants ──────────────────────────────────────────────
SW_RESTORE = 9
VK_CONTROL = 0x11
VK_V = 0x56
VK_A = 0x41
VK_C = 0x43
VK_RETURN = 0x0D
VK_BACK = 0x08
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


# ── Win32 helpers ─────────────────────────────────────────────────

def _find_window_by_title(title: str) -> Optional[int]:
    """Find window by exact title match. Returns hwnd or None."""
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        return hwnd
    # enum all windows, case-insensitive match
    results = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _cb(h, _):
        n = user32.GetWindowTextLengthW(h)
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, buf, n + 1)
            if title.lower() in buf.value.lower():
                results.append(h)
        return True
    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return results[0] if results else None


def _activate_window(hwnd: int):
    """Bring window to foreground."""
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)


def _send_key(vk: int, up: bool = False, extended: bool = False):
    """Send a single key event via SendInput (preferred over keybd_event)."""
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_uint), ("time", ctypes.c_uint),
                    ("dwExtraInfo", ctypes.c_void_p)]
    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]
        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_uint), ("u", _U)]
    flags = 0
    if up:
        flags |= KEYEVENTF_KEYUP
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT(type=1, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=None))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _send_combo(keys: list[tuple[int, bool]]):
    """Send a key combination. keys = [(VK, extended), ...].
    Presses all in order, releases in reverse."""
    for vk, ext in keys:
        _send_key(vk, up=False, extended=ext)
        time.sleep(0.02)
    for vk, ext in reversed(keys):
        _send_key(vk, up=True, extended=ext)
        time.sleep(0.02)


def _ctrl_key(vk_char: int):
    """Send Ctrl + key."""
    _send_combo([(VK_CONTROL, False), (vk_char, False)])
    time.sleep(0.1)


def _clipboard_get() -> str:
    """Read text from clipboard."""
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except Exception:
        return ""


def _clipboard_set(text: str):
    """Write text to clipboard."""
    try:
        import pyperclip
        pyperclip.copy(text)
    except Exception:
        pass


# ── MarvisBridge ──────────────────────────────────────────────────

class MarvisBridge(Bridge):
    """通过 Win32 键盘模拟 + 剪贴板与 Marvis 桌面 AI 交互。

    策略：粘贴 → 回车 → 等待 → 全选复制 → 读剪贴板。
    不依赖 UIA 控件树（Marvis 是 Qt 应用，不暴露内部控件）。
    """

    def __init__(
        self,
        app_name: str = "Marvis",
        timeout: int = 300,
        poll_interval: float = 1.0,
        max_idle_polls: int = 3,
    ):
        self.app_name = app_name
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_idle_polls = max_idle_polls

    def _is_window_alive(self, hwnd: int) -> bool:
        """Check if window handle is still valid."""
        return bool(user32.IsWindow(hwnd))

    def run(self, task: Task, **kwargs) -> BridgeResult:
        timeout = kwargs.get("timeout", self.timeout)
        start = time.time()

        # ── 1. Find & activate window ──────────────────────────
        hwnd = _find_window_by_title(self.app_name)
        if hwnd is None:
            return BridgeResult(
                success=False, output="",
                error=f"Window not found: {self.app_name}. Is Marvis running?",
            )
        _activate_window(hwnd)

        # ── 2. Save current clipboard ──────────────────────────
        saved = _clipboard_get()

        # ── 3. Paste task content ──────────────────────────────
        _clipboard_set(task.content)
        time.sleep(0.1)
        _ctrl_key(VK_V)  # Ctrl+V
        time.sleep(0.3)

        # ── 4. Send message ────────────────────────────────────
        #     Use keybd_event for Enter (more reliable than SendInput in some apps)
        _activate_window(hwnd)  # ensure focus
        time.sleep(0.1)
        user32.keybd_event(VK_RETURN, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.5)

        # ── 5. Wait for response via clipboard polling ─────────
        #     Click conversation area → select-all → copy
        #     After Enter, focus stays in input box; click upper half first.
        prev = ""
        idle_count = 0
        deadline = start + timeout
        output = ""

        # Get window rect for clicking conversation area
        rect = ctypes.create_string_buffer(16)
        ctypes.windll.user32.GetWindowRect(hwnd, rect)
        w_left = int.from_bytes(rect[0:4], 'little')
        w_top = int.from_bytes(rect[4:8], 'little')
        w_right = int.from_bytes(rect[8:12], 'little')
        w_bottom = int.from_bytes(rect[12:16], 'little')
        # Click upper 1/3 for conversation area, horizontal center
        conv_x = (w_left + w_right) // 2
        conv_y = w_top + (w_bottom - w_top) // 3

        while time.time() < deadline:
            time.sleep(self.poll_interval)

            if not self._is_window_alive(hwnd):
                return BridgeResult(
                    success=False, output=output,
                    error="Marvis window closed during wait",
                )

            # activate, click conversation area, select-all, copy
            _activate_window(hwnd)
            time.sleep(0.05)
            # Click conversation area (upper portion) to move focus away from input
            ctypes.windll.user32.SetCursorPos(conv_x, conv_y)
            time.sleep(0.05)
            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
            time.sleep(0.1)
            _ctrl_key(VK_A)     # Ctrl+A : select all conversation
            time.sleep(0.1)
            _ctrl_key(VK_C)     # Ctrl+C : copy
            time.sleep(0.2)

            current = _clipboard_get()

            if current == prev:
                idle_count += 1
                if idle_count >= self.max_idle_polls and current.strip():
                    # response stabilized
                    output = current
                    break
            else:
                prev = current
                idle_count = 0

        else:
            # timed out — use whatever we have
            output = prev

        # ── 6. Restore clipboard ───────────────────────────────
        _clipboard_set(saved)

        # ── 7. Extract just the response ───────────────────────
        #     The clipboard will contain the full conversation.
        #     Strip the user's message from the front.
        response = self._extract_response(output, task.content)
        duration_ms = int((time.time() - start) * 1000)

        return BridgeResult(
            success=bool(response.strip()),
            output=response.strip() or output.strip(),
            duration_ms=duration_ms,
        )

    def _extract_response(self, full_text: str, sent_message: str) -> str:
        """Extract the last AI response from the full conversation text."""
        if not full_text.strip():
            return ""
        # If the full text contains the sent message, take everything after it
        if sent_message in full_text:
            parts = full_text.split(sent_message, 1)
            if len(parts) > 1:
                return parts[-1].strip()
        # Otherwise, return as-is (may reflect a different message layout)
        return full_text.strip()

    def check_available(self) -> bool:
        try:
            hwnd = _find_window_by_title(self.app_name)
            return hwnd is not None
        except Exception:
            return False

    def check_auth(self) -> bool:
        return self.check_available()
