"""Marvis MCP 配置写入脚本。

检测 Marvis 配置文件位置，追加 ai-hub MCP server 配置。
幂等操作：已存在则跳过，不覆盖其他配置。

用法：
    python -m ai_hub.scripts.configure_marvis_mcp
    或直接执行：
    python scripts/configure_marvis_mcp.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


# ─── 配置常量 ───
AI_HUB_MCP_CONFIG = {
    "ai-hub": {
        "command": "python",
        "args": ["-m", "ai_hub.adapters.marvis_mcp_server"],
    }
}

# 可能的 Marvis 配置文件路径（按优先级排序）
MARVIS_CONFIG_CANDIDATES = [
    Path(os.environ.get("APPDATA", ""), "Marvis", "marvis-client.config.json"),
    Path(os.environ.get("LOCALAPPDATA", ""), "Marvis", "marvis-client.config.json"),
    Path(os.environ.get("APPDATA", ""), "Marvis", "config.json"),
    Path(os.environ.get("LOCALAPPDATA", ""), "Marvis", "config.json"),
]


def find_marvis_config() -> Path | None:
    """查找 Marvis 配置文件。返回找到的第一个路径，或 None。"""
    for candidate in MARVIS_CONFIG_CANDIDATES:
        if candidate.exists():
            print(f"[OK] Found existing config: {candidate}")
            return candidate

    # 广搜 AppData 下的 Marvis 相关文件
    for root_str in [os.environ.get("APPDATA", ""), os.environ.get("LOCALAPPDATA", "")]:
        root = Path(root_str)
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                name_lower = path.name.lower()
                if "mcp" in name_lower and path.suffix in (".json",):
                    print(f"[INFO] Found MCP-related file: {path}")
                    if "marvis" in name_lower or "client" in name_lower:
                        return path
        except PermissionError:
            continue

    return None


def configure_mcp(config_path: Path) -> bool:
    """在 Marvis 配置文件中追加 ai-hub MCP server 配置。"""
    existing_config = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                existing_config = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[WARN] Failed to read existing config: {e}")

    # 备份
    if existing_config and config_path.exists():
        backup_path = config_path.with_suffix(
            f".config.json.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        shutil.copy2(config_path, backup_path)
        print(f"[OK] Backup created: {backup_path}")

    # 合并 mcpServers
    if "mcpServers" not in existing_config:
        existing_config["mcpServers"] = {}

    # 检查是否已配置 ai-hub
    if "ai-hub" in existing_config.get("mcpServers", {}):
        existing_cfg = existing_config["mcpServers"]["ai-hub"]
        if existing_cfg == AI_HUB_MCP_CONFIG["ai-hub"]:
            print("[SKIP] ai-hub MCP config already exists and is up to date.")
            return True
        else:
            print(f"[WARN] ai-hub MCP config exists but differs. Overwriting.")

    # 写入/更新
    existing_config["mcpServers"].update(AI_HUB_MCP_CONFIG)

    config_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(existing_config, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"[OK] Config written to: {config_path}")
        print(f"\nConfig content (mcpServers section):")
        print(json.dumps(existing_config["mcpServers"], indent=2))
        return True
    except OSError as e:
        print(f"[ERROR] Failed to write config: {e}")
        return False


def verify_python_and_module() -> bool:
    """验证 python 环境和 ai_hub 模块可用性。"""
    print(f"[CHECK] Python: {sys.executable} ({sys.version})")

    try:
        import mcp
        # mcp 1.x 没有 __version__ 属性，尝试从 importlib.metadata 取
        try:
            from importlib.metadata import version as _pkg_version
            mcp_ver = _pkg_version("mcp")
        except Exception:
            mcp_ver = "(unknown)"
        print(f"[CHECK] mcp SDK: {mcp_ver}")
    except ImportError:
        print("[ERROR] mcp package not installed. Run: pip install mcp")
        return False

    # ai-hub 项目布局是平铺的（core/、adapters/ 等在根目录），代码内部
    # 使用 `from core.xxx` / `from adapters.xxx` 平铺 import。
    # 所以我们检查的是这种平铺 import，而不是 `import ai_hub.xxx`（那是
    # editable install 后才有的虚拟包名）。
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    print(f"[CHECK] ai-hub project root: {project_root}")

    try:
        from core.registry import CapabilityRegistry  # noqa: F401
        from core.task import Task  # noqa: F401
        from core.result import Result  # noqa: F401
        print("[CHECK] core modules: OK")
    except ImportError as e:
        print(f"[ERROR] Cannot import ai-hub core modules: {e}")
        print(f"        Ensure {project_root} contains core/, router/, adapters/, providers/")
        return False

    try:
        from adapters import marvis_mcp_server
        print("[CHECK] adapters.marvis_mcp_server: OK")
    except ImportError as e:
        print(f"[ERROR] Cannot import marvis_mcp_server: {e}")
        return False

    return True


def main() -> int:
    """主函数。"""
    print("=" * 60)
    print("  ai-hub Marvis MCP Configuration Tool")
    print(f"  Time: {datetime.now().isoformat()}")
    print("=" * 60)
    print()

    # Step 1: 验证环境
    print("[Step 1] Verifying Python environment...")
    if not verify_python_and_module():
        print("\n[FAIL] Environment check failed. Fix errors above and retry.")
        return 1
    print()

    # Step 2: 查找配置文件
    print("[Step 2] Finding Marvis config file...")
    config_path = find_marvis_config()
    if config_path is None:
        print("\n[WARN] Could not find Marvis config file automatically.")
        env_path = os.environ.get("MARVIS_CONFIG_PATH")
        if env_path:
            config_path = Path(env_path)
            print(f"\n[INFO] Using MARVIS_CONFIG_PATH={env_path}")
        else:
            default_path = Path(os.environ.get("APPDATA", ""), "Marvis", "marvis-client.config.json")
            print(f"\n[INFO] Will create new config at: {default_path}")
            config_path = default_path
    print()

    # Step 3: 写入配置
    print("[Step 3] Writing MCP configuration...")
    if not configure_mcp(config_path):
        print("\n[FAIL] Configuration write failed.")
        return 1
    print()

    # Step 4: 打印验证步骤
    print("=" * 60)
    print("  Configuration complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Restart Marvis client completely")
    print("  2. Open Marvis settings -> MCP / Tools")
    print("  3. Verify 'ai-hub' appears in the tools list")
    print('  4. In a Marvis chat, type: "用 ai-hub 解释一下 CAP theorem"')
    print("  5. Check that ai-hub tool is called and results appear")
    print()
    print("Manual test (without Marvis):")
    print('  echo \'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\' | \\')
    print("  python -m ai_hub.adapters.marvis_mcp_server")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
