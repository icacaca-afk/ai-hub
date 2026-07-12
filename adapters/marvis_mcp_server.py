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
        ("providers.marvis.provider", "MarvisProvider"),
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
def run_provider(
    capability: str,
    content: str,
    context: dict | None = None,
) -> dict:
    """通过 ai-hub 执行任务。

    Args:
        capability: 能力标签，如：
            - text.generate — 生成文本
            - code.generate — 生成代码
            - general.chat — 通用对话
            - search.web — 网络搜索
            - text.analyze — 分析文本
            - text.summarize — 总结文本
            - code.debug — 调试代码
            - browser.navigate — 浏览器导航
            （完整列表见 ai_hub.core.capabilities.CAPABILITIES）
        content: 任务内容（自然语言描述）
        context: 附加上下文（可选），如 {"language": "python"}

    Returns:
        {
            "success": bool,       // 是否成功
            "output": str,         // 执行结果文本
            "error": str | null,   // 错误信息（成功时为 null）
            "provider": str,       // 执行的 Provider 名称
            "capability": str,     // 实际使用的能力标签
            "duration_ms": int,    // 执行耗时（毫秒）
            "artifacts": list,     // 产物文件路径列表
        }
    """
    start = time.time()

    try:
        # 1. 创建 Task
        task = Task(
            content=content,
            capabilities=[capability],
            context=context or {},
        )

        # 2. 路由 + 执行
        router = _get_router()
        provider = router.route(task)

        if provider is None:
            available_caps = []
            try:
                reg = _get_registry()
                for p in reg.all():
                    available_caps.extend(p.capabilities)
            except Exception:
                pass
            return {
                "success": False,
                "output": "",
                "error": (
                    f"No available provider for capability '{capability}'. "
                    f"Available capabilities from registered providers: "
                    f"{sorted(set(available_caps)) or '(none)'}"
                ),
                "provider": None,
                "capability": capability,
                "duration_ms": int((time.time() - start) * 1000),
                "artifacts": [],
            }

        # 3. 执行（Router.execute 内部做 select_bridge + bridge.run + 转换 Result）
        result: Result = router.execute(task)
        duration_ms = int((time.time() - start) * 1000)

        # 4. 记录历史
        try:
            history = HistoryStore()
            history.add(task.content, capability, provider.name, result)
        except Exception as e:
            logger.warning(f"Failed to record history: {e}")

        # 5. 返回结构化结果
        return {
            "success": result.is_success,
            "output": result.output,
            "error": result.error,
            "provider": result.provider,
            "capability": capability,
            "duration_ms": duration_ms,
            "artifacts": result.artifacts,
        }

    except Exception as e:
        logger.exception(f"run_provider failed: {e}")
        return {
            "success": False,
            "output": "",
            "error": f"Internal error: {type(e).__name__}: {e}",
            "provider": None,
            "capability": capability,
            "duration_ms": int((time.time() - start) * 1000),
            "artifacts": [],
        }


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
