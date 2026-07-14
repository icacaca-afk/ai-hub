# AI Hub — CLI 入口
#
# 用法：
#   ai-hub ask "写一个 Python HTTP 服务"
#   ai-hub history
#   ai-hub status
#   ai-hub quota
#   ai-hub caps

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core.registry import CapabilityRegistry
from core.task import Task
from core.history import HistoryStore
from router.router import Router
from cli.explain_route import cmd_explain_route


def _build_registry() -> CapabilityRegistry:
    """构建 CapabilityRegistry。

    V0.1.1: 全量注册 5 个 Provider，验证 Zero-Modification KPI。
    - demo       (FakeBridge)  — 基线
    - gemini_cli (CLIBridge)   — V0.1 真实接入
    - stub       (CLIBridge)   — V0.1.1 架构验证（同类型第二个）
    - openai_api (APIBridge)   — V0.1 真实接入
    - qoder      (CLIBridge)   — 注册但 CLI 不可用时自动降级
    """
    registry = CapabilityRegistry()

    from providers.demo.provider import DemoProvider
    registry.register(DemoProvider())

    from providers.gemini.provider import GeminiCLIProvider
    registry.register(GeminiCLIProvider())

    from providers.stub.provider import StubProvider
    registry.register(StubProvider())

    from providers.openai_api.provider import OpenAIAPIProvider
    registry.register(OpenAIAPIProvider())

    from providers.qoder.provider import QoderProvider
    registry.register(QoderProvider())

    from providers.fake_browser.provider import FakeBrowserProvider
    registry.register(FakeBrowserProvider())

    from providers.web_ai.provider import WebAIProvider
    registry.register(WebAIProvider())

    return registry


def cmd_ask(args: list[str]) -> None:
    if not args:
        print('Usage: ai-hub ask "<task description>"')
        sys.exit(1)

    text = " ".join(args)
    registry = _build_registry()
    from core.quota import QuotaManager
    quota = QuotaManager()
    router = Router(registry, quota_manager=quota)
    history = HistoryStore()

    # 创建 Task
    task = Task.from_text(text)

    print(f"[Router] Capabilities: {task.capabilities}")

    # 路由
    provider = router.route(task)

    if provider is None:
        print(f"[Router] No available provider for capabilities: {task.capabilities}")
        print(f"[Router] Task: {text}")
        sys.exit(1)

    print(f"[Router] Provider:     {provider.display_name}")
    bridge = provider.select_bridge(task)
    print(f"[Router] Bridge:       {type(bridge).__name__}")
    print()

    # 执行
    start = time.time()
    result = router.execute(task)
    duration = int((time.time() - start) * 1000)

    if "duration_ms" not in result.metadata:
        result.metadata["duration_ms"] = duration

    # 记录历史
    history.add(task.content, ",".join(task.capabilities), provider.name, result)

    # 输出
    print(result.output)

    if result.artifacts:
        print(f"\n[Artifacts]")
        for a in result.artifacts:
            print(f"  - {a}")

    if not result.is_success:
        print(f"\n[Error] {result.error}", file=sys.stderr)
        sys.exit(1)


def cmd_history(args: list[str]) -> None:
    history = HistoryStore()
    limit = 10
    for arg in args:
        if arg.isdigit():
            limit = int(arg)

    records = history.recent(limit)
    if not records:
        print("No history yet.")
        return

    print(f"Recent {len(records)} tasks:\n")
    for i, r in enumerate(records, 1):
        status_icon = "✅" if r["status"] == "success" else "❌"
        print(f"  {i}. {status_icon} [{r['provider']}] {r['input'][:60]}")
        print(f"     {r['timestamp']} | {r['task_type']} | {r['duration_ms']}ms")


def cmd_status(args: list[str]) -> None:
    """Show comprehensive runtime status.

    分区块展示：Providers / Bridges / Runtime / Quota / MCP
    支持 --json 输出给机器读。
    """
    json_output = "--json" in args

    registry = _build_registry()
    providers = registry.all()

    from core.health_registry import HealthRegistry
    from core.quota import QuotaManager
    from core.session import SessionManager

    hr = HealthRegistry()
    reports = hr.get_all(providers, lazy=False)

    if json_output:
        _status_json(reports, providers, json_output=True)
        return

    # ── 版本信息 ──
    print("AI Hub Status — Health Framework v0.6")

    # ── 计算检查时间差 ──
    now = datetime.now(timezone.utc)
    newest_check = max((r.checked_at for r in reports.values()), default=now)
    ago = _humanize_ago((now - newest_check).total_seconds())

    # ── Providers ──
    print()
    print(f"┅┅┅┅┅┅┅┅ Providers  (checked {ago}) ┅┅┅┅┅┅┅┅")
    print(f"{'NAME':<16} {'STATUS':<14} {'AUTH':<6} {'QUOTA':<6} {'TYPE':<10} {'MESSAGE'}")
    print("-" * 80)

    status_icons = {
        "healthy": "✓ healthy",
        "degraded": "⚡ degraded",
        "unknown": "? unknown",
        "unavailable": "✗ unavailable",
    }

    for p in providers:
        r = reports[p.name]
        icon = status_icons.get(r.status, r.status)
        auth = "✓" if r.authenticated else "✗" if r.authenticated is False else "?"
        quota = "✓" if r.quota_ok else "✗" if r.quota_ok is False else "?"
        # 读取 metadata.health_type（V0.6 新增）
        ptype = getattr(p.metadata, "health_type", "") or "?"
        if not ptype:
            bridge_name = type(p.bridge).__name__
            if "CLI" in bridge_name: ptype = "CLI"
            elif "API" in bridge_name: ptype = "API"
            elif "Browser" in bridge_name: ptype = "Browser"
        # 截断 message
        msg = r.message[:30] if r.message else ""
        print(f"{p.name:<16} {icon:<14} {auth:<6} {quota:<6} {ptype:<10} {msg}")

    # ── Bridges ──
    print()
    print("┅┅┅┅┅┅┅┅ Bridges ┅┅┅┅┅┅┅┅")
    bridge_types = set()
    for p in providers:
        bridge_types.add(type(p.bridge).__name__)
    for bt in sorted(bridge_types):
        print(f"{bt:<20} ✓")

    # ── Runtime ──
    try:
        sm = SessionManager()
        all_sessions = sm.list()
        active = sum(1 for s in all_sessions if s.status == "active")
        print()
        print("┅┅┅┅┅┅┅┅ Runtime ┅┅┅┅┅┅┅┅")
        print(f"{'Sessions':<20} {len(all_sessions)}")
        print(f"{'Active':<20} {active}")
        sm.close()
    except Exception:
        pass

    # ── Quota ──
    print()
    print("┅┅┅┅┅┅┅┅ Quota ┅┅┅┅┅┅┅┅")
    try:
        qm = QuotaManager()
        quota_status = qm.status()
        if quota_status:
            for q in quota_status:
                pct = "∞" if q["total"] == -1 else f"{q['remaining']/q['total']*100:.0f}%"
                flag = " ⚠ EXHAUSTED" if q["exhausted"] else ""
                print(f"{q['provider']:<20} {pct:>6}{flag}")
        else:
            print("(no quota data)")
    except Exception:
        print("(quota db not available)")

    # ── MCP ──
    print()
    print("┅┅┅┅┅┅┅┅ MCP ┅┅┅┅┅┅┅┅")
    try:
        from tools.mcp_server import server as mcp_server_module
        print("  MCP server module found")
    except Exception:
        print("  (MCP server not loaded)")

    print()


def _status_json(reports, providers, json_output=True):
    """JSON 格式输出。"""
    import json
    output = {
        "providers": {},
        "bridges": [],
        "timestamp": "",
    }
    for p in providers:
        if p.name in reports:
            r = reports[p.name]
            output["providers"][p.name] = r.to_dict()
            output["timestamp"] = r.checked_at.isoformat()

    bridge_types = set()
    for p in providers:
        bridge_types.add(type(p.bridge).__name__)
    output["bridges"] = sorted(bridge_types)

    print(json.dumps(output, indent=2, ensure_ascii=False))


def _humanize_ago(seconds: float) -> str:
    """将秒数转为人性化的时间描述。"""
    seconds = abs(seconds)
    if seconds < 1:
        return "just now"
    elif seconds < 5:
        return f"{int(seconds)}s ago"
    elif seconds < 60:
        return f"{int(seconds)}s ago"
    elif seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s ago" if s > 0 else f"{m}m ago"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m ago" if m > 0 else f"{h}h ago"


def cmd_quota(args: list[str]) -> None:
    from core.quota import QuotaManager

    if args and args[0] == "log":
        qm = QuotaManager()
        provider = args[1] if len(args) > 1 else None
        logs = qm.log(provider)
        if not logs:
            print("No quota log entries.")
            return
        print(f"{'Time':<22} {'Provider':<16} {'Amt':>3} {'Rem':>6}")
        print("-" * 51)
        for l in logs:
            ts = l["created_at"][:19].replace("T", " ")
            print(f"{ts:<22} {l['provider_name']:<16} {l['amount']:>3} {l['remaining']:>6}")
        return

    if args and args[0] == "reset":
        qm = QuotaManager()
        if len(args) > 1:
            qm.reset(args[1])
            print(f"Quota reset for: {args[1]}")
        else:
            qm.reset_all()
            print("All quotas reset.")
        return

    qm = QuotaManager()
    print(qm.summary())


def cmd_caps(args: list[str]) -> None:
    """列出所有能力标签和对应的 Provider。"""
    registry = _build_registry()
    from core.capabilities import CAPABILITIES

    print("AI Hub — Capabilities\n")
    for cap, desc in sorted(CAPABILITIES.items()):
        providers = registry.find_by_capability(cap)
        provider_names = ", ".join(p.name for p in providers) or "(none)"
        print(f"  {cap:<20} {desc:<12} -> {provider_names}")


def cmd_session(args: list[str]) -> None:
    from core.session import SessionManager

    if not args:
        print("Usage:")
        print('  ai-hub session list [provider]   List sessions')
        print('  ai-hub session create <provider>  Create a session')
        print('  ai-hub session show <id>          Show session details')
        print('  ai-hub session checkpoint <id>    Checkpoint a session')
        print('  ai-hub session resume <id>        Resume a session')
        print('  ai-hub session destroy <id>       Destroy a session')
        return

    sub = args[0]
    mgr = SessionManager()

    if sub == "list":
        provider = args[1] if len(args) > 1 else None
        sessions = mgr.list(provider)
        if not sessions:
            print("No sessions.")
            return
        print(f"{'ID':<12} {'Provider':<14} {'Status':<14} {'Updated':<20}")
        print("-" * 62)
        for s in sessions:
            sid = s.session_id[:8]
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s.updated_at))
            print(f"{sid:<12} {s.provider_name:<14} {s.status:<14} {ts:<20}")

    elif sub == "create":
        if len(args) < 2:
            print("Usage: ai-hub session create <provider>")
            sys.exit(1)
        s = mgr.create(args[1])
        print(f"Created session: {s.session_id}")
        print(f"  Provider: {s.provider_name}")
        print(f"  Status:   {s.status}")

    elif sub == "show":
        if len(args) < 2:
            print("Usage: ai-hub session show <id>")
            sys.exit(1)
        s = mgr.get(args[1])
        if not s:
            print(f"Session not found: {args[1]}")
            sys.exit(1)
        print(f"Session:    {s.session_id}")
        print(f"Provider:   {s.provider_name}")
        print(f"Status:     {s.status}")
        print(f"Created:    {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s.created_at))}")
        print(f"Updated:    {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s.updated_at))}")
        if s.context:
            print(f"Context:")
            for k, v in s.context.items():
                print(f"  {k}: {v}")

    elif sub == "checkpoint":
        if len(args) < 2:
            print("Usage: ai-hub session checkpoint <id>")
            sys.exit(1)
        try:
            s = mgr.checkpoint(args[1])
            print(f"Checkpointed: {s.session_id} ({s.status})")
        except (KeyError, ValueError) as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif sub == "resume":
        if len(args) < 2:
            print("Usage: ai-hub session resume <id>")
            sys.exit(1)
        try:
            s = mgr.resume(args[1])
            print(f"Resumed: {s.session_id} ({s.status})")
        except (KeyError, ValueError) as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif sub == "destroy":
        if len(args) < 2:
            print("Usage: ai-hub session destroy <id>")
            sys.exit(1)
        ok = mgr.destroy(args[1])
        if ok:
            print(f"Destroyed: {args[1]}")
        else:
            print(f"Session not found or already destroyed: {args[1]}")
            sys.exit(1)

    else:
        print(f"Unknown subcommand: {sub}")
        print("Available: list, create, show, checkpoint, resume, destroy")
        sys.exit(1)

    mgr.close()


def cmd_doctor(args: list[str]) -> None:
    """诊断 Provider 问题，给出可操作的修复建议。

    类似 `pip check` 的诊断思路：
    - 逐 Provider 检查可执行文件/依赖/认证/配置
    - 输出 ✓ / ✗ / ⚠ 状态
    - 每个 ✗ 附带修复建议
    """
    import shutil
    import subprocess
    import os as _os

    registry = _build_registry()
    providers = registry.all()

    from core.health_registry import HealthRegistry

    hr = HealthRegistry()
    reports = hr.get_all(providers, lazy=False)

    print("AI Hub Doctor — Diagnostics Report\n")

    issues = 0
    for p in providers:
        r = reports[p.name]
        name = p.metadata.display_name or p.name
        ptype = getattr(p.metadata, "health_type", "") or "unknown"

        print(f"▸ {name} ({p.name})")
        print(f"  type: {ptype}")

        fixes: list[str] = []

        if ptype == "cli":
            # CLI Provider：检查可执行文件
            exe = None
            bridge = p.bridge
            if hasattr(bridge, "command_template"):
                exe = bridge.command_template.split()[0] if bridge.command_template else None
            elif hasattr(bridge, "command"):
                exe = bridge.command.split()[0] if bridge.command else None

            if exe:
                found = shutil.which(exe)
                if found:
                    print(f"  executable: ✓ {found}")
                else:
                    print(f"  executable: ✗ {exe} not found in PATH")
                    fixes.append(f"Install '{exe}' or add it to PATH")
                    issues += 1

            # 认证检查
            if r.authenticated is False:
                print(f"  auth: ✗ not authenticated")
                if "gemini" in p.name.lower():
                    fixes.append("Set GEMINI_API_KEY environment variable")
                elif "qoder" in p.name.lower():
                    fixes.append("Run 'qoderclicn login' or set QODER_API_KEY")
                issues += 1
            elif r.authenticated is True:
                print(f"  auth: ✓")
            else:
                print(f"  auth: ? can't determine")

            # 额度
            if r.quota_ok is False:
                print(f"  quota: ✗ exhausted")
                fixes.append("Quota exhausted — wait for reset or upgrade plan")
                issues += 1

        elif ptype == "api":
            # API Provider：检查 API Key 环境变量
            env_key = None
            if "openai" in p.name.lower():
                env_key = "OPENAI_API_KEY"
            if env_key:
                val = _os.environ.get(env_key, "")
                if val:
                    masked = val[:6] + "***" if len(val) > 6 else "***"
                    print(f"  {env_key}: ✓ {masked}")
                else:
                    print(f"  {env_key}: ✗ not set")
                    fixes.append(f"Set {env_key} environment variable")
                    issues += 1
            else:
                print(f"  auth: {r.authenticated}")

            if r.quota_ok is False:
                print(f"  quota: ✗")
                issues += 1

        elif ptype == "browser":
            # Browser Provider：检查 Playwright + Chromium
            try:
                import playwright
                print(f"  playwright: ✓ installed")
            except ImportError:
                print(f"  playwright: ✗ not installed")
                fixes.append("Run 'pip install playwright && playwright install chromium'")
                issues += 1
            else:
                try:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(headless=True)
                        browser.close()
                    print(f"  chromium: ✓ launchable")
                except Exception as e:
                    print(f"  chromium: ✗ {e}")
                    fixes.append("Run 'playwright install chromium'")
                    issues += 1

        # 综合状态
        if r.status == "healthy":
            print(f"  health: {r.status}")
        elif r.status == "degraded":
            print(f"  health: {r.status} — {r.message}")
        elif r.status == "unavailable":
            print(f"  health: {r.status} — {r.message}")
        else:
            print(f"  health: {r.status}")

        # 修复建议
        if fixes:
            for fix in fixes:
                print(f"  🔧 {fix}")

        print()

    # ── 总结 ──
    if issues == 0:
        print(f"✓ All {len(providers)} providers healthy.")
    else:
        print(f"Found {issues} issue(s) across {len(providers)} provider(s).")
        print("Run the suggested commands above to fix.")


def cmd_benchmark(args: list[str]) -> None:
    """Benchmark Provider 延迟和成功率。

    对每个 healthy Provider 发送简单任务，测量：
    - 延迟（ms）
    - 成功/失败
    - 输出预览

    用法：
      ai-hub benchmark              # 默认跑 1 轮
      ai-hub benchmark --rounds 3   # 跑 3 轮取平均
      ai-hub benchmark --json       # JSON 输出
    """
    import json as _json
    import time as _time

    json_output = "--json" in args
    rounds = 1
    for i, a in enumerate(args):
        if a == "--rounds" and i + 1 < len(args):
            rounds = int(args[i + 1])

    registry = _build_registry()
    providers = registry.all()

    from core.health_registry import HealthRegistry
    from core.task import Task
    from core.result import Result

    hr = HealthRegistry()
    reports = hr.get_all(providers, lazy=False)

    # 只 benchmark healthy 的 Provider（排除 demo/stub/fake_browser）
    skip = {"demo", "stub", "fake_browser"}
    benchable = [
        p for p in providers
        if p.name not in skip and reports[p.name].is_healthy
    ]

    if not benchable:
        print("No healthy providers to benchmark.")
        return

    if not json_output:
        print(f"AI Hub Benchmark — {len(benchable)} provider(s), {rounds} round(s)\n")

    results: list[dict] = []
    bench_task = Task.from_text("Reply with exactly: OK")

    for p in benchable:
        latencies: list[int] = []
        successes = 0
        last_output = ""
        last_error = ""

        for r in range(rounds):
            start = _time.time()
            try:
                bridge = p.select_bridge(bench_task)
                br = bridge.run(bench_task)
                elapsed_ms = int((_time.time() - start) * 1000)

                if br.success:
                    successes += 1
                    latencies.append(elapsed_ms)
                    last_output = br.output[:60].strip()
                else:
                    last_error = br.error or "Unknown error"
            except Exception as e:
                elapsed_ms = int((_time.time() - start) * 1000)
                last_error = str(e)

        avg_latency = int(sum(latencies) / len(latencies)) if latencies else 0
        min_latency = min(latencies) if latencies else 0
        max_latency = max(latencies) if latencies else 0
        success_rate = successes / rounds * 100

        entry = {
            "provider": p.name,
            "display_name": p.metadata.display_name,
            "rounds": rounds,
            "successes": successes,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency,
            "min_latency_ms": min_latency,
            "max_latency_ms": max_latency,
            "last_output": last_output,
            "last_error": last_error,
        }
        results.append(entry)

    if json_output:
        print(_json.dumps({"benchmark": results}, indent=2, ensure_ascii=False))
        return

    # ── 表格输出 ──
    print(f"{'PROVIDER':<16} {'SUCCESS':<10} {'AVG':<8} {'MIN':<8} {'MAX':<8} {'OUTPUT'}")
    print("-" * 72)
    for r in results:
        succ = f"{r['successes']}/{r['rounds']}"
        avg = f"{r['avg_latency_ms']}ms"
        mn = f"{r['min_latency_ms']}ms"
        mx = f"{r['max_latency_ms']}ms"
        out = r['last_output'] or r['last_error'][:30]
        print(f"{r['provider']:<16} {succ:<10} {avg:<8} {mn:<8} {mx:<8} {out}")

    print()
    print("Benchmark complete.")


def main() -> None:
    if len(sys.argv) < 2:
        print("AI Hub — One Task. Any AI. Any Runtime.\n")
        print("Usage:")
        print('  ai-hub ask "<task>"    Execute a task')
        print("  ai-hub history [N]      Show recent N tasks (default 10)")
        print("  ai-hub status           Show provider status")
        print("  ai-hub doctor           Diagnose provider issues")
        print("  ai-hub benchmark         Benchmark provider latency & success")
        print("  ai-hub quota            Show quota status")
        print("  ai-hub caps             Show capability mapping")
        print('  ai-hub explain-route "<task>"  Explain routing decision')
        print("  ai-hub session <cmd>    Manage sessions")
        sys.exit(0)

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "ask": cmd_ask,
        "history": cmd_history,
        "status": cmd_status,
        "quota": cmd_quota,
        "caps": cmd_caps,
        "session": cmd_session,
        "doctor": cmd_doctor,
        "benchmark": cmd_benchmark,
        "explain-route": cmd_explain_route,
    }

    if command not in commands:
        print(f"Unknown command: {command}")
        print(f"Available commands: {', '.join(commands.keys())}")
        sys.exit(1)

    commands[command](args)


if __name__ == "__main__":
    main()
