"""RuntimeRegistry tests."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.runtime_registry import RuntimeRegistry
from core.bridge import FakeBridge


def test_bind_get():
    rr = RuntimeRegistry()
    bridge = FakeBridge()
    rr.bind("session-1", bridge)
    assert rr.get_bridge("session-1") is bridge
    print("OK test_bind_get")


def test_get_unbound():
    rr = RuntimeRegistry()
    assert rr.get_bridge("nonexistent") is None
    print("OK test_get_unbound")


def test_unbind():
    rr = RuntimeRegistry()
    bridge = FakeBridge()
    rr.bind("session-1", bridge)
    assert rr.unbind("session-1") is True
    assert rr.get_bridge("session-1") is None
    print("OK test_unbind")


def test_unbind_nonexistent():
    rr = RuntimeRegistry()
    assert rr.unbind("nonexistent") is False
    print("OK test_unbind_nonexistent")


def test_is_bound():
    rr = RuntimeRegistry()
    bridge = FakeBridge()
    assert rr.is_bound("s1") is False
    rr.bind("s1", bridge)
    assert rr.is_bound("s1") is True
    print("OK test_is_bound")


def test_active_sessions():
    rr = RuntimeRegistry()
    rr.bind("s1", FakeBridge())
    rr.bind("s2", FakeBridge())
    rr.bind("s3", FakeBridge())
    active = rr.active_sessions()
    assert len(active) == 3
    assert "s1" in active
    assert "s2" in active
    assert "s3" in active
    print("OK test_active_sessions")


def test_count():
    rr = RuntimeRegistry()
    assert rr.count() == 0
    rr.bind("s1", FakeBridge())
    assert rr.count() == 1
    rr.bind("s2", FakeBridge())
    assert rr.count() == 2
    rr.unbind("s1")
    assert rr.count() == 1
    print("OK test_count")


def test_clear():
    rr = RuntimeRegistry()
    rr.bind("s1", FakeBridge())
    rr.bind("s2", FakeBridge())
    n = rr.clear()
    assert n == 2
    assert rr.count() == 0
    print("OK test_clear")


def test_rebind():
    rr = RuntimeRegistry()
    b1 = FakeBridge()
    b2 = FakeBridge()
    rr.bind("s1", b1)
    assert rr.get_bridge("s1") is b1
    rr.bind("s1", b2)
    assert rr.get_bridge("s1") is b2
    print("OK test_rebind")


if __name__ == "__main__":
    tests = [
        test_bind_get, test_get_unbound, test_unbind, test_unbind_nonexistent,
        test_is_bound, test_active_sessions, test_count, test_clear, test_rebind,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\nRuntimeRegistry: {len(tests)-failed}/{len(tests)} passed")
    if failed:
        sys.exit(1)
