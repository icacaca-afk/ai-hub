"""ai-hub 作为 Marvis MCP Server。

让 Marvis 客户端通过 stdio MCP 协议调用 ai-hub 的 Provider 能力。
ai-hub core 零修改 —— 所有新代码在 adapters/ 目录。

用法：
    python -m ai_hub.adapters.marvis_mcp_server

架构：
    Marvis (MCP Client) --stdio--> ai-hub MCP Server --> CapabilityRegistry --> Provider --> Bridge --> Result
"""

from __future__ import annotations

import sys
import logging
import time
from pathlib import Path

# ── 启动兼容：让三种入口方式都能跑通 ─────────────────────
# 1) python -m ai_hub.adapters.marvis_mcp_server（editable install 之后）
# 2) python -m adapters.marvis_mcp_server（PYTHONPATH 含 ai-hub 根目录时）
# 3) python adapters/marvis_mcp_server.py（直接脚本，需把根目录加进 sys.path）
#
# 当 `core` `router` 等包无法被直接 import 时，把项目根目录加入 sys.path。
# 这种"自动检测"避免了"先装再跑"或"PYTHONPATH 忘了设"的脆弱性。

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent

def _ensure_project_root_on_path() -> None:
    """如果当前 import 路径里找不到 core/router，就把项目根目录加进 sys.path。"""
    needed = ("core", "router")
    for mod in needed:
        try:
            __import__(mod)
            return
        except ImportError:
            continue
    root = str(_PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
        # importlib 缓存清理
        for mod in needed:
            sys.modules.pop(mod, None)

_ensure_project_root_on_path()

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from mcp.server.fastmcp import FastMCP

from core.registry import CapabilityRegistry
from core.task import Task
from core.result import Result
from core.history import HistoryStore
from core.quota import QuotaManager
from router.router import Router

logger = logging.getLogger("ai-hub.mcp")

# ─── 全局单例（模块级，避免每次调用重建） ───
_registry: CapabilityRegistry | None = None
_router: Router | None = None


def _get_registry() -> CapabilityRegistry:
    """延迟初始化 CapabilityRegistry（复用 cli/main.py 的注册模式）。"""
    global _registry
    if _registry is not None:
        return _registry

    _registry = CapabilityRegistry()

    # 按 cli/main.py._build_registry() 的顺序注册所有 Provider
    # 每个 Provider 自带 Bridge 和 capability 声明
    _provider_entries = [
        ("providers.demo.provider", "DemoProvider"),
        ("providers.gemini.provider", "GeminiCLIProvider"),
        ("providers.stub.provider", "StubProvider"),
        ("providers.openai_api.provider", "OpenAIAPIProvider"),
        ("providers.qoder.provider", "QoderProvider"),
        ("providers.fake_browser.provider", "FakeBrowserProvider"),
    ]

    registered_count = 0
    for module_path, class_name in _provider_entries:
        try:
            mod = __import__(module_path, fromlist=[class_name])
            cls = getattr(mod, class_name)
            instance = cls()
            _registry.register(instance)
            registered_count += 1
            logger.debug(f"Registered provider: {instance.name}")
        except Exception as e:
            logger.warning(f"Skipping provider {class_name}: {e}")

    logger.info(f"CapabilityRegistry initialized with {registered_count} providers")
    return _registry


def _get_router() -> Router:
    """延迟初始化 Router（含 QuotaManager）。"""
    global _router
    if _router is not None:
        return _router

    registry = _get_registry()
    quota = QuotaManager()
    _router = Router(registry, quota_manager=quota)
    return _router


# ─── FastMCP 实例 ───
mcp = FastMCP(
    "ai-hub",
    instructions=(
        "ai-hub 统一执行 runtime。"
        "通过 run_provider 工具执行任务，支持的能力标签见 capability 参数说明。"
        "常用能力：text.generate（文本生成）、code.generate（代码生成）、"
        "general.chat（通用对话）、search.web（网络搜索）、text.analyze（文本分析）等。"
    ),
)


@mcp.tool()
def run_provider(task: dict) -> dict:
    """通过 ai-hub 执行任务。

    Args:
        task: 任务描述，JSON 对象，字段如下：
            - capability (str, 必填): 能力标签，如 "code.generate"、"general.chat"、
              "search.web"、"text.summarize" 等（完整列表见 list_capabilities）
            - content (str, 必填): 任务内容（自然语言描述）
            - context (dict, 可选): 附加上下文，如 {"language": "python"}
            - session (str, 可选): 会话 ID，用于多轮对话
            - timeout (int, 可选): 超时秒数，默认 300

    Returns:
        成功时：
        {
            "success": true,
            "output": str,          // 执行结果文本
            "error": null,
            "code": null,
            "retryable": false,
            "provider": str,        // 执行的 Provider 名称
            "capability": str,      // 实际使用的能力标签
            "duration_ms": int,     // 执行耗时（毫秒）
            "artifacts": list,      // 产物文件路径列表
        }
        失败时：
        {
            "success": false,
            "output": "",
            "error": str,           // 人类可读错误描述
            "code": str,            // 错误码，如 "NO_PROVIDER"、"PROVIDER_TIMEOUT"、"INTERNAL"
            "retryable": bool,      // 是否值得重试
            "provider": str | null,
            "capability": str,
            "duration_ms": int,
            "artifacts": [],
        }
    """
    start = time.time()

    # 错误码常量
    _ERROR_CODES = {
        "NO_PROVIDER": (False, "No available provider"),
        "PROVIDER_FAILED": (True, "Provider execution failed"),
        "BAD_REQUEST": (False, "Invalid task"),
        "INTERNAL": (False, "Internal error"),
    }

    def _fail(code: str, message: str, provider: str | None = None) -> dict:
        retryable = _ERROR_CODES.get(code, (False, ""))[0]
        return {
            "success": False,
            "output": "",
            "error": message,
            "code": code,
            "retryable": retryable,
            "provider": provider,
            "capability": task.get("capability", ""),
            "duration_ms": int((time.time() - start) * 1000),
            "artifacts": [],
        }

    try:
        # 1. 参数校验
        if not isinstance(task, dict):
            return _fail("BAD_REQUEST", f"task must be a dict, got {type(task).__name__}")

        capability = task.get("capability")
        content = task.get("content")

        if not capability or not isinstance(capability, str):
            return _fail("BAD_REQUEST", "task.capability is required and must be a string")
        if not content or not isinstance(content, str):
            return _fail("BAD_REQUEST", "task.content is required and must be a string")

        context = task.get("context") or {}

        # 2. 创建 Task
        task_obj = Task(
            content=content,
            capabilities=[capability],
            context=context,
        )

        # 3. 路由 + 执行
        router = _get_router()
        provider = router.route(task_obj)

        if provider is None:
            available_caps = []
            try:
                reg = _get_registry()
                for p in reg.all():
                    available_caps.extend(p.capabilities)
            except Exception:
                pass
            return _fail(
                "NO_PROVIDER",
                f"No available provider for capability '{capability}'. "
                f"Available: {sorted(set(available_caps)) or '(none)'}",
            )

        # 4. 执行
        result: Result = router.execute(task_obj)
        duration_ms = int((time.time() - start) * 1000)

        # 5. 记录历史
        try:
            history = HistoryStore()
            history.add(task_obj.content, capability, provider.name, result)
        except Exception as e:
            logger.warning(f"Failed to record history: {e}")

        # 6. 返回结构化结果
        if result.is_success:
            return {
                "success": True,
                "output": result.output,
                "error": None,
                "code": None,
                "retryable": False,
                "provider": result.provider,
                "capability": capability,
                "duration_ms": duration_ms,
                "artifacts": result.artifacts,
            }
        else:
            # 优先使用 Result 自身的 code/retryable；如果未设置则从 error 推断
            if result.code:
                code = result.code
            else:
                err_str = result.error or ""
                if "timeout" in err_str.lower() or "timed out" in err_str.lower():
                    code = "PROVIDER_TIMEOUT"
                elif "quota" in err_str.lower():
                    code = "QUOTA_EXHAUSTED"
                elif "not found" in err_str.lower() or "window" in err_str.lower():
                    code = "PROVIDER_UNAVAILABLE"
                else:
                    code = "PROVIDER_FAILED"
            retryable = result.retryable if result.code else code in ("PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE")
            return {
                "success": False,
                "output": result.output,
                "error": result.error,
                "code": code,
                "retryable": retryable,
                "provider": result.provider,
                "capability": capability,
                "duration_ms": duration_ms,
                "artifacts": result.artifacts,
            }

    except Exception as e:
        logger.exception(f"run_provider failed: {e}")
        return _fail("INTERNAL", f"{type(e).__name__}: {e}")


@mcp.tool()
def list_providers() -> dict:
    """列出 ai-hub 当前已注册的所有 Provider 及其状态。

    Returns:
        {
            "providers": [
                {
                    "name": str,
                    "display_name": str,
                    "available": bool,
                    "capabilities": list[str],
                    "priority": int,
                    "bridge_type": str,
                }
            ]
        }
    """
    try:
        registry = _get_registry()
        providers = registry.all()
        return {
            "providers": [
                {
                    "name": p.name,
                    "display_name": p.display_name,
                    "available": p.available(),
                    "capabilities": p.capabilities,
                    "priority": p.priority,
                    "bridge_type": type(p.bridge).__name__,
                }
                for p in providers
            ],
        }
    except Exception as e:
        return {"providers": [], "error": str(e)}


@mcp.tool()
def list_capabilities() -> dict:
    """列出 ai-hub 支持的所有能力标签。

    Returns:
        {"capabilities": {"label": "description", ...}}
    """
    try:
        from core.capabilities import CAPABILITIES
        return {"capabilities": dict(CAPABILITIES)}
    except Exception as e:
        return {"capabilities": {}, "error": str(e)}


# ─── 入口 ───
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    mcp.run(transport="stdio")
