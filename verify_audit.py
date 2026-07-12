"""V0.4.1 验收脚本 —— 给 ChatGPT 审查的客观证据。

不做任何代码修改，只采集事实。
"""
import sys
import json
import time
import subprocess
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
PYTHON = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe"


def run(cmd, cwd=None, timeout=30, **kw):
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=cwd or str(PROJECT_ROOT), timeout=timeout,
        encoding="utf-8", errors="replace", **kw
    )


def safe_print(s):
    """强制 UTF-8 输出，避开 Windows GBK 控制台。"""
    if isinstance(s, bytes):
        s = s.decode("utf-8", errors="replace")
    try:
        sys.stdout.buffer.write((s + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
    except Exception:
        try:
            print(s.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass


def section(title):
    safe_print("\n" + "=" * 70)
    safe_print(f"  {title}")
    safe_print("=" * 70)


# ── 1. Git 状态 ────────────────────────────────────────────
section("1. Git status: core/ + router/ 零修改")
res = run(["git", "log", "--oneline", "-5"])
safe_print(res.stdout or "(no commits)")

res = run(["git", "status", "--short"])
safe_print("[Working tree]")
safe_print(res.stdout or "  (clean)")

res = run(["git", "diff", "--stat", "core/", "router/"])
safe_print("[git diff core/ + router/ since HEAD]")
safe_print(res.stdout if res.stdout else "  (NO changes - core/router FROZEN)")

# ── 2. mcp SDK 检查 ──────────────────────────────────────
section("2. mcp SDK version")
res = run([PYTHON, "-c", "import mcp; from importlib.metadata import version; print('mcp', version('mcp'))"])
safe_print(res.stdout or res.stderr)

# ── 3. MCP stdio 握手测试 ───────────────────────────────
section("3. MCP stdio handshake (initialize + tools/list + list_providers)")

mcp_proc = subprocess.Popen(
    [PYTHON, str(PROJECT_ROOT / "adapters" / "marvis_mcp_server.py")],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    cwd=str(PROJECT_ROOT),
)

# initialize
mcp_proc.stdin.write(json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "audit-verify", "version": "1.0"},
    },
}) + "\n")
mcp_proc.stdin.flush()
time.sleep(1.5)

# initialized notification
mcp_proc.stdin.write(json.dumps({
    "jsonrpc": "2.0", "method": "notifications/initialized"
}) + "\n")
mcp_proc.stdin.flush()
time.sleep(0.5)

# tools/list
mcp_proc.stdin.write(json.dumps({
    "jsonrpc": "2.0", "id": 2, "method": "tools/list"
}) + "\n")
mcp_proc.stdin.flush()
time.sleep(1.5)

# tools/call list_providers
mcp_proc.stdin.write(json.dumps({
    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
    "params": {"name": "list_providers", "arguments": {}},
}) + "\n")
mcp_proc.stdin.flush()
time.sleep(1.5)

mcp_proc.stdin.close()
try:
    out, err = mcp_proc.communicate(timeout=5)
except subprocess.TimeoutExpired:
    mcp_proc.kill()
    out, err = mcp_proc.communicate()

safe_print("[STDOUT from MCP server]")
for line in out.splitlines():
    if line.strip():
        try:
            parsed = json.loads(line)
            safe_print(json.dumps(parsed, indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            safe_print(f"  (non-JSON) {line}")
if err.strip():
    safe_print("[STDERR]")
    safe_print("  " + err.replace("\n", "\n  ")[:800])

# ── 4. Marvis 配置文件状态 ──────────────────────────────
section("4. Marvis config file state")
marvis_cfg = Path(os.environ["APPDATA"]) / "Marvis" / "marvis-client.config.json"
print(f"Path: {marvis_cfg}")
print(f"Exists: {marvis_cfg.exists()}")
if marvis_cfg.exists():
    with open(marvis_cfg, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    servers = cfg.get("mcpServers", {})
    print(f"mcpServers count: {len(servers)}")
    for name, srv in servers.items():
        safe_print(f"  - {name}: {srv}")

# ── 5. 关键文件存在性 ─────────────────────────────────────
section("5. V0.4.1 deliverable file existence")
files = [
    "adapters/__init__.py",
    "adapters/marvis_mcp_server.py",
    "scripts/configure_marvis_mcp.py",
    "docs/adr/0007-marvis-integration-via-mcp.md",
    "V041_VERIFICATION_REPORT.md",
]
for f in files:
    fp = PROJECT_ROOT / f
    size = fp.stat().st_size if fp.exists() else 0
    marker = "[OK]" if fp.exists() else "[MISS]"
    print(f"  {marker} {f:50s} {size:6d} bytes")

# ── 6. 验证三种入口方式 ───────────────────────────────
section("6. MCP Server three entry-point compatibility")
env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
entrypoints = [
    ("(1) python adapters/marvis_mcp_server.py",
     [PYTHON, str(PROJECT_ROOT / "adapters" / "marvis_mcp_server.py")]),
    ("(2) python -m adapters.marvis_mcp_server",
     [PYTHON, "-m", "adapters.marvis_mcp_server"]),
    ("(3) from adapters import marvis_mcp_server",
     [PYTHON, "-c", "import sys; sys.path.insert(0, r'" + str(PROJECT_ROOT).replace("\\", "\\\\") + r"'); import adapters.marvis_mcp_server; print('IMPORT_OK')"]),
]
for desc, cmd in entrypoints:
    p = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", cwd=str(PROJECT_ROOT), env=env,
    )
    if "import" in desc.lower() and "-c" in cmd:
        # no stdio for pure import
        out, err = p.communicate(timeout=10)
        success = "IMPORT_OK" in out
    else:
        p.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}},
        }) + "\n")
        p.stdin.flush()
        time.sleep(1.5)
        p.stdin.close()
        try:
            out, err = p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
        success = '"serverInfo"' in out or "ai-hub" in out
    marker = "[OK]" if success else "[FAIL]"
    print(f"  {marker} {desc}")
    if not success and err:
        print(f"      err: {err[:200]}")
