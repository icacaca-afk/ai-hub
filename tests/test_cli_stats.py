# tests/test_cli_stats.py
# V0.9.7 — `ai-hub stats` CLI 测试（ADR-0020）
#
# 覆盖：
# - 空 DB 输出
# - 全局统计（人类可读）
# - --plan <id> / --provider <name> / --since --until 过滤
# - --json 输出（包含 version/source/filters/derived stats）
# - ai-hub stats 命令已注册到 main usage
# - stats 全部从 events 派生（不调 PlanStore，ADR-0020 决策 8）
#
# 测试隔离：单元测试注入 tmp_path store；subprocess 测试用 AI_HUB_DB_PATH env

import json
import os
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def _run_cli(*args, timeout=30, db_path=None):
    """运行 ai-hub CLI 命令（subprocess），可用 db_path 隔离 DB。"""
    cmd = [sys.executable, "-m", "cli.main"] + list(args)
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}
    if db_path is not None:
        env["AI_HUB_DB_PATH"] = str(db_path)
    r = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        cwd=PROJECT_ROOT, env=env, timeout=timeout,
    )
    return r.returncode, r.stdout or "", r.stderr or ""


def _seed_events(db_path, plan_id: str = "p-001", status: str = "success",
                 steps: int = 1, provider_name: str = "fake",
                 provider_latency_ms: int = 200,
                 server_metrics: dict | None = None,
                 started_ts: str = "2026-07-17T10:00:00.000Z",
                 finished_ts: str = "2026-07-17T10:00:01.000Z"):
    """直接构造 SQLiteExecutionStore 注入 events（避免跑 plan CLI）。"""
    from planner.sqlite_execution_store import SQLiteExecutionStore
    from planner.execution_event import ExecutionEvent

    with SQLiteExecutionStore(db_path=str(db_path)) as store:
        events = [
            ExecutionEvent(type="plan_started", plan_id=plan_id, timestamp=started_ts),
            ExecutionEvent(type="planner_started", plan_id=plan_id, timestamp=started_ts),
            ExecutionEvent(type="planner_finished", plan_id=plan_id, timestamp=started_ts,
                           data={"step_count": steps}),
        ]
        for i in range(steps):
            events.append(ExecutionEvent(
                type="step_started", plan_id=plan_id, step_id=f"step-{i}",
                timestamp=started_ts, data={"index": i},
            ))
            events.append(ExecutionEvent(
                type="provider_selected", plan_id=plan_id, step_id=f"step-{i}",
                provider="ScoreRouter", timestamp=started_ts,
            ))
            data = {"status": status}
            if server_metrics is not None:
                data["server_metrics"] = server_metrics
            events.append(ExecutionEvent(
                type="provider_finished", plan_id=plan_id, step_id=f"step-{i}",
                provider=provider_name, timestamp=started_ts,
                latency_ms=provider_latency_ms, data=data,
            ))
            events.append(ExecutionEvent(
                type="step_finished", plan_id=plan_id, step_id=f"step-{i}",
                timestamp=finished_ts,
                data={"status": status, "latency_ms": provider_latency_ms},
            ))
        events.append(ExecutionEvent(
            type="plan_finished", plan_id=plan_id, timestamp=finished_ts,
            data={"status": status, "steps": steps, "success": steps if status == "success" else 0, "failed": 0 if status == "success" else 1},
        ))
        for e in events:
            store.handle(e)


# ── 命令注册 ──

class TestStatsCommandRegistration:
    """stats 命令在 main.py 已注册。"""

    def test_stats_in_usage(self, tmp_path):
        """ai-hub 无参数（默认 usage）包含 stats 提示。"""
        code, out, _ = _run_cli(db_path=str(tmp_path / "test.db"))
        assert code == 0
        assert "stats" in out.lower()


# ── 空 DB ──

class TestStatsEmptyDB:
    """空 DB 的 stats 输出。"""

    def test_empty_db_json(self, tmp_path):
        """空 DB --json：所有计数为 0。"""
        db = tmp_path / "exec.db"
        code, out, _ = _run_cli("stats", "--json", db_path=str(db))
        assert code == 0
        payload = json.loads(out)
        assert payload["version"] == "0.9.7"
        assert payload["source"] == "sqlite"
        assert payload["plans"]["total"] == 0
        assert payload["plans"]["success"] == 0
        assert payload["steps"]["total"] == 0
        assert payload["events"]["total"] == 0
        assert payload["providers"] == []
        assert payload["total_cost_usd"] == 0.0

    def test_empty_db_human(self, tmp_path):
        """空 DB 人类可读输出。"""
        db = tmp_path / "exec.db"
        code, out, _ = _run_cli("stats", db_path=str(db))
        assert code == 0
        assert "AI Hub Statistics — v0.9.7" in out
        assert "Plans: 0 total" in out


# ── 过滤 ──

class TestStatsFilters:
    """--plan / --provider / --since / --until 过滤测试。"""

    def test_filter_by_plan(self, tmp_path):
        """--plan 过滤：只统计指定 plan。"""
        db = tmp_path / "exec.db"
        _seed_events(db, plan_id="p-001")
        _seed_events(db, plan_id="p-002")

        code, out, _ = _run_cli("stats", "--plan", "p-001", "--json", db_path=str(db))
        assert code == 0
        payload = json.loads(out)
        assert payload["plans"]["total"] == 1
        assert payload["filters"]["plan_id"] == "p-001"

    def test_filter_by_provider(self, tmp_path):
        """--provider 过滤。"""
        db = tmp_path / "exec.db"
        _seed_events(db, plan_id="p-001", provider_name="openai_api")
        _seed_events(db, plan_id="p-002", provider_name="openai_compatible")

        code, out, _ = _run_cli("stats", "--provider", "openai_api", "--json", db_path=str(db))
        assert code == 0
        payload = json.loads(out)
        # 只统计 openai_api 的 provider_finished events
        # 但 plan_started/finished 也算入 plans/steps
        assert payload["filters"]["provider"] == "openai_api"
        # provider_finished 来自 openai_api，所以 providers 列表只有 openai_api
        provider_names = [p["name"] for p in payload["providers"]]
        assert provider_names == ["openai_api"]

    def test_filter_by_since_until(self, tmp_path):
        """--since / --until 时间范围过滤。"""
        db = tmp_path / "exec.db"
        # Plan 1: 2026-01-01
        _seed_events(
            db, plan_id="p-001",
            started_ts="2026-01-01T00:00:00.000Z",
            finished_ts="2026-01-01T00:00:01.000Z",
        )
        # Plan 2: 2026-07-17
        _seed_events(
            db, plan_id="p-002",
            started_ts="2026-07-17T00:00:00.000Z",
            finished_ts="2026-07-17T00:00:01.000Z",
        )

        code, out, _ = _run_cli(
            "stats", "--since", "2026-06-01T00:00:00.000Z", "--until", "2026-12-31T00:00:00.000Z",
            "--json", db_path=str(db),
        )
        assert code == 0
        payload = json.loads(out)
        assert payload["plans"]["total"] == 1
        assert payload["filters"]["since"] == "2026-06-01T00:00:00.000Z"
        assert payload["filters"]["until"] == "2026-12-31T00:00:00.000Z"


# ── JSON 输出 schema ──

class TestStatsJsonSchema:
    """--json 输出 schema 测试。"""

    def test_json_schema_complete(self, tmp_path):
        """JSON 输出包含所有 ADR-0020 决策 3 要求的字段。"""
        db = tmp_path / "exec.db"
        _seed_events(
            db, plan_id="p-001", steps=1, status="success",
            server_metrics={"token_in": 100, "token_out": 50, "cost_usd": 0.001},
        )

        code, out, _ = _run_cli("stats", "--json", db_path=str(db))
        assert code == 0
        payload = json.loads(out)

        # 必须包含的字段（ADR-0020 决策 3）
        assert "version" in payload
        assert "source" in payload
        assert "db_path" in payload
        assert "filters" in payload
        # plans / steps / events / providers / latency / cost
        assert "plans" in payload
        assert payload["plans"]["total"] == 1
        assert payload["plans"]["success"] == 1
        assert "success_rate" in payload["plans"]
        assert "steps" in payload
        assert "events" in payload
        assert "providers" in payload
        assert len(payload["providers"]) == 1
        # provider stats 字段
        p = payload["providers"][0]
        for key in ("name", "calls", "success_count", "failed_count",
                    "avg_latency_ms", "total_token_in", "total_token_out", "total_cost_usd"):
            assert key in p
        # latency
        assert "latency" in payload
        assert "avg_plan_ms" in payload["latency"]
        assert "avg_step_ms" in payload["latency"]
        # total cost
        assert "total_cost_usd" in payload


# ── 人类可读输出 ──

class TestStatsHumanOutput:
    """人类可读输出测试。"""

    def test_human_output_includes_key_sections(self, tmp_path):
        """人类可读输出包含关键 section。"""
        db = tmp_path / "exec.db"
        _seed_events(
            db, plan_id="p-001", steps=1,
            server_metrics={"token_in": 100, "token_out": 50, "cost_usd": 0.001},
        )

        code, out, _ = _run_cli("stats", db_path=str(db))
        assert code == 0
        # 关键 section
        assert "AI Hub Statistics — v0.9.7" in out
        assert "Time Range:" in out
        assert "Plans: 1 total" in out
        assert "Success: 1" in out
        assert "Providers:" in out
        assert "fake" in out
        assert "Average Plan Latency:" in out
        assert "Total Estimated Cost:" in out
        # ChatGPT V0.9.6 建议：cost 标注 "est."
        assert "est." in out

    def test_human_output_unicode_safe(self, tmp_path):
        """人类可读输出 Windows 终端兼容（用 est. 替代 ≈）。"""
        db = tmp_path / "exec.db"
        _seed_events(
            db, plan_id="p-001", steps=1,
            server_metrics={"token_in": 100, "token_out": 50, "cost_usd": 0.001},
        )

        code, out, _ = _run_cli("stats", db_path=str(db))
        assert code == 0
        # ChatGPT V0.9.6 Q6 建议：≈ 在 Windows 终端有兼容问题，用 "est."
        assert "≈" not in out
        assert "est." in out
