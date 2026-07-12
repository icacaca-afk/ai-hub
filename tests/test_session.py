"""SessionManager tests. Isolated temp DB per test."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.session import Session, SessionManager


def _mgr():
    return SessionManager(tempfile.mktemp())


def test_create():
    mgr = _mgr()
    s = mgr.create("gemini_cli")
    assert s.session_id
    assert s.provider_name == "gemini_cli"
    assert s.status == "active"
    assert s.context == {}
    assert s.is_active()
    mgr.close()
    print("OK test_create")


def test_create_with_context():
    mgr = _mgr()
    s = mgr.create("openai_api", context={"model": "deepseek", "history": []})
    assert s.context["model"] == "deepseek"
    assert len(s.context["history"]) == 0
    mgr.close()
    print("OK test_create_with_context")


def test_get():
    mgr = _mgr()
    s = mgr.create("demo")
    found = mgr.get(s.session_id)
    assert found is not None
    assert found.session_id == s.session_id
    assert mgr.get("nonexistent") is None
    mgr.close()
    print("OK test_get")


def test_list():
    mgr = _mgr()
    mgr.create("gemini_cli")
    mgr.create("openai_api")
    mgr.create("gemini_cli")

    all_sessions = mgr.list()
    assert len(all_sessions) == 3

    gemini_only = mgr.list("gemini_cli")
    assert len(gemini_only) == 2

    openai_only = mgr.list("openai_api")
    assert len(openai_only) == 1

    assert mgr.list("nonexistent") == []
    mgr.close()
    print("OK test_list")


def test_checkpoint():
    mgr = _mgr()
    s = mgr.create("demo")
    s2 = mgr.checkpoint(s.session_id, context={"last_output": "hello"})
    assert s2.status == "checkpointed"
    assert s2.is_checkpointed()
    assert s2.context["last_output"] == "hello"
    mgr.close()
    print("OK test_checkpoint")


def test_checkpoint_merge():
    mgr = _mgr()
    s = mgr.create("demo", context={"a": 1})
    mgr.checkpoint(s.session_id, context={"b": 2})
    s2 = mgr.get(s.session_id)
    assert s2.context == {"a": 1, "b": 2}
    mgr.close()
    print("OK test_checkpoint_merge")


def test_resume():
    mgr = _mgr()
    s = mgr.create("demo")
    mgr.checkpoint(s.session_id)
    s2 = mgr.resume(s.session_id)
    assert s2.status == "active"
    assert s2.is_active()
    mgr.close()
    print("OK test_resume")


def test_resume_not_checkpointed():
    mgr = _mgr()
    s = mgr.create("demo")
    try:
        mgr.resume(s.session_id)
        assert False, "Should raise ValueError"
    except ValueError:
        pass
    mgr.close()
    print("OK test_resume_not_checkpointed")


def test_destroy():
    mgr = _mgr()
    s = mgr.create("demo")
    ok = mgr.destroy(s.session_id)
    assert ok is True
    s2 = mgr.get(s.session_id)
    assert s2.is_destroyed()
    mgr.close()
    print("OK test_destroy")


def test_destroy_twice():
    mgr = _mgr()
    s = mgr.create("demo")
    assert mgr.destroy(s.session_id) is True
    assert mgr.destroy(s.session_id) is False
    mgr.close()
    print("OK test_destroy_twice")


def test_destroy_nonexistent():
    mgr = _mgr()
    assert mgr.destroy("nonexistent") is False
    mgr.close()
    print("OK test_destroy_nonexistent")


def test_checkpoint_destroyed():
    mgr = _mgr()
    s = mgr.create("demo")
    mgr.destroy(s.session_id)
    try:
        mgr.checkpoint(s.session_id)
        assert False, "Should raise ValueError"
    except ValueError:
        pass
    mgr.close()
    print("OK test_checkpoint_destroyed")


def test_resume_destroyed():
    mgr = _mgr()
    s = mgr.create("demo")
    mgr.destroy(s.session_id)
    try:
        mgr.resume(s.session_id)
        assert False, "Should raise ValueError"
    except ValueError:
        pass
    mgr.close()
    print("OK test_resume_destroyed")


def test_persist():
    db = tempfile.mktemp()
    mgr1 = SessionManager(db)
    s = mgr1.create("demo", context={"key": "value"})
    mgr1.checkpoint(s.session_id)
    mgr1.close()

    mgr2 = SessionManager(db)
    s2 = mgr2.get(s.session_id)
    assert s2 is not None
    assert s2.provider_name == "demo"
    assert s2.context["key"] == "value"
    assert s2.status == "checkpointed"
    mgr2.close()
    print("OK test_persist")


def test_full_lifecycle():
    mgr = _mgr()
    s = mgr.create("gemini_cli", context={"messages": []})
    assert s.is_active()

    # 模拟第一次 Task
    mgr.checkpoint(s.session_id, context={"messages": ["hello"]})
    assert s.is_checkpointed() or mgr.get(s.session_id).is_checkpointed()

    # 恢复
    s = mgr.resume(s.session_id)
    assert s.is_active()

    # 模拟第二次 Task
    mgr.checkpoint(s.session_id, context={"messages": ["hello", "world"]})
    s = mgr.get(s.session_id)
    assert len(s.context["messages"]) == 2

    # 销毁
    assert mgr.destroy(s.session_id) is True
    assert mgr.get(s.session_id).is_destroyed()
    mgr.close()
    print("OK test_full_lifecycle")


if __name__ == "__main__":
    tests = [
        test_create, test_create_with_context, test_get, test_list,
        test_checkpoint, test_checkpoint_merge, test_resume,
        test_resume_not_checkpointed, test_destroy, test_destroy_twice,
        test_destroy_nonexistent, test_checkpoint_destroyed,
        test_resume_destroyed, test_persist, test_full_lifecycle,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\nSession: {len(tests)-failed}/{len(tests)} passed")
    if failed:
        sys.exit(1)
