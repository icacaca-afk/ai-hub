# tests/test_execution_event.py
# V0.9.4 — ExecutionEvent 数据类测试（ADR-0017）
#
# 覆盖：
# - 8 种 event_type 构造
# - 字段默认值（event_id 自动生成 UUID）
# - to_dict() 序列化
# - ISO 8601 时间戳
# - 字段全部 Optional 除 type/plan_id

import json
import pytest

from planner.execution_event import ExecutionEvent


class TestExecutionEventConstruction:
    """ExecutionEvent 构造与字段。"""

    def test_minimal_event(self):
        """仅 type + plan_id 必填。"""
        e = ExecutionEvent(type="plan_started", plan_id="p-001")
        assert e.type == "plan_started"
        assert e.plan_id == "p-001"

    def test_event_id_auto_generated(self):
        """event_id 默认生成 UUID。"""
        e1 = ExecutionEvent(type="plan_started", plan_id="p-001")
        e2 = ExecutionEvent(type="plan_started", plan_id="p-001")
        # 每个 event 唯一
        assert e1.event_id != e2.event_id
        # 32 字符 hex
        assert len(e1.event_id) == 32
        assert all(c in "0123456789abcdef" for c in e1.event_id)

    def test_event_id_can_be_explicit(self):
        """event_id 可显式指定（用于 replay / deduplication）。"""
        e = ExecutionEvent(type="plan_started", plan_id="p-001", event_id="custom-id-123")
        assert e.event_id == "custom-id-123"

    def test_timestamp_is_iso8601_utc(self):
        """timestamp 是 ISO 8601 格式（以 Z 结尾）。"""
        e = ExecutionEvent(type="plan_started", plan_id="p-001")
        assert e.timestamp.endswith("Z")
        # 形如 2026-07-17T12:00:00.000Z
        assert "T" in e.timestamp
        assert len(e.timestamp) >= 20

    def test_optional_fields_default_none(self):
        """step_id / provider / latency_ms 默认 None。"""
        e = ExecutionEvent(type="plan_started", plan_id="p-001")
        assert e.step_id is None
        assert e.provider is None
        assert e.latency_ms is None

    def test_data_default_empty_dict(self):
        """data 默认空 dict。"""
        e = ExecutionEvent(type="plan_started", plan_id="p-001")
        assert e.data == {}

    def test_all_8_event_types(self):
        """8 种 event_type 都能构造（ADR-0017 D1）。"""
        types = [
            "plan_started",
            "planner_started",
            "planner_finished",
            "step_started",
            "provider_selected",
            "provider_finished",
            "step_finished",
            "plan_finished",
        ]
        for t in types:
            e = ExecutionEvent(type=t, plan_id="p-001")
            assert e.type == t

    def test_step_event_with_step_id(self):
        """step-level event 含 step_id。"""
        e = ExecutionEvent(
            type="step_started",
            plan_id="p-001",
            step_id="step-0",
            data={"index": 0, "content_preview": "hello"},
        )
        assert e.step_id == "step-0"
        assert e.data["index"] == 0
        assert e.data["content_preview"] == "hello"

    def test_provider_event_with_latency(self):
        """provider event 含 provider + latency_ms。"""
        e = ExecutionEvent(
            type="provider_finished",
            plan_id="p-001",
            step_id="step-0",
            provider="gemini_cli",
            latency_ms=200,
        )
        assert e.provider == "gemini_cli"
        assert e.latency_ms == 200


class TestExecutionEventToDict:
    """to_dict() 序列化。"""

    def test_to_dict_basic(self):
        e = ExecutionEvent(type="plan_started", plan_id="p-001")
        d = e.to_dict()
        assert d["type"] == "plan_started"
        assert d["plan_id"] == "p-001"
        assert "event_id" in d
        assert "timestamp" in d
        assert d["step_id"] is None
        assert d["provider"] is None
        assert d["latency_ms"] is None
        assert d["data"] == {}

    def test_to_dict_full(self):
        e = ExecutionEvent(
            type="provider_finished",
            plan_id="p-001",
            step_id="step-0",
            provider="fake",
            latency_ms=200,
            data={"status": "success"},
        )
        d = e.to_dict()
        assert d["type"] == "provider_finished"
        assert d["step_id"] == "step-0"
        assert d["provider"] == "fake"
        assert d["latency_ms"] == 200
        assert d["data"] == {"status": "success"}

    def test_to_dict_data_isolated(self):
        """to_dict 复制 data（避免引用泄漏）。"""
        e = ExecutionEvent(type="plan_started", plan_id="p-001", data={"k": 1})
        d = e.to_dict()
        d["data"]["k"] = 999
        # 原始 data 不受影响
        assert e.data == {"k": 1}

    def test_to_dict_is_json_serializable(self):
        """to_dict 输出可 JSON 序列化。"""
        e = ExecutionEvent(
            type="step_started",
            plan_id="p-001",
            step_id="step-0",
            data={"content_preview": "你好世界"},
        )
        d = e.to_dict()
        # 包含中文
        json_str = json.dumps(d, ensure_ascii=False)
        assert "你好世界" in json_str


class TestExecutionEventPostelCompliance:
    """Postel's Law：发送保守，接收容忍。"""

    def test_consumer_can_ignore_unknown_fields(self):
        """Consumer 解析事件时，忽略未知字段是安全的。"""
        e = ExecutionEvent(
            type="custom_event_v2",  # 未来类型
            plan_id="p-001",
            step_id="step-0",
            data={"future_field": 123},
        )
        d = e.to_dict()
        # Consumer 仅取它需要的字段
        assert d["type"] == "custom_event_v2"
        assert d["plan_id"] == "p-001"
        # 忽略未识别的 future_field（在 data 子键中）
        # Consumer 不需要展开 data 即可工作
        assert d["data"] == {"future_field": 123}

    def test_consumer_can_handle_missing_optional(self):
        """Consumer 处理缺 Optional 字段时，应 fallback 到默认值。"""
        # 模拟老 consumer 接收新事件
        e = ExecutionEvent(type="plan_started", plan_id="p-001")
        d = e.to_dict()

        # Consumer 读取时容忍 None
        step_id = d.get("step_id")  # None
        provider = d.get("provider")  # None
        latency = d.get("latency_ms")  # None

        assert step_id is None
        assert provider is None
        assert latency is None
