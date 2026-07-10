"""QuotaManager tests. Each test uses an isolated temp DB."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.quota import QuotaManager


def _qm():
    import tempfile
    return QuotaManager(tempfile.mktemp(suffix=".db"))


def test_init():
    qm = _qm()
    assert qm.status() == []
    qm.close()
    print("OK test_init")


def test_ensure():
    qm = _qm()
    qm.ensure("p", total=100, quota_type="daily")
    s = qm.status("p")
    assert len(s) == 1
    assert s[0]["total"] == 100
    assert s[0]["used"] == 0
    qm.close()
    print("OK test_ensure")


def test_ensure_idempotent():
    qm = _qm()
    qm.ensure("p", total=100)
    qm.ensure("p", total=200)
    s = qm.status("p")
    assert s[0]["total"] == 100
    qm.close()
    print("OK test_ensure_idempotent")


def test_consume():
    qm = _qm()
    qm.ensure("p", total=100)
    assert qm.consume("p") is True
    assert qm.remaining("p") == 99
    assert qm.consume("p", amount=10) is True
    assert qm.remaining("p") == 89
    qm.close()
    print("OK test_consume")


def test_exhausted():
    qm = _qm()
    qm.ensure("p", total=3)
    assert qm.consume("p") is True
    assert qm.consume("p") is True
    assert qm.consume("p") is True
    assert qm.consume("p") is False
    assert qm.remaining("p") == 0
    assert qm.exhausted("p") is True
    assert qm.is_available("p") is False
    qm.close()
    print("OK test_exhausted")


def test_unlimited():
    qm = _qm()
    qm.ensure("p", total=-1)
    assert qm.remaining("p") == -1
    assert qm.exhausted("p") is False
    for _ in range(1000):
        assert qm.consume("p") is True
    assert qm.remaining("p") == -1
    qm.close()
    print("OK test_unlimited")


def test_unregistered():
    qm = _qm()
    assert qm.remaining("unknown") == -1
    assert qm.is_available("unknown") is True
    assert qm.consume("unknown") is True
    qm.close()
    print("OK test_unregistered")


def test_reset_one():
    qm = _qm()
    qm.ensure("p", total=100)
    qm.consume("p", amount=50)
    assert qm.remaining("p") == 50
    qm.reset("p")
    assert qm.remaining("p") == 100
    qm.close()
    print("OK test_reset_one")


def test_reset_all():
    qm = _qm()
    qm.ensure("a", total=10)
    qm.ensure("b", total=20)
    qm.consume("a", amount=5)
    qm.consume("b", amount=10)
    qm.reset_all()
    assert qm.remaining("a") == 10
    assert qm.remaining("b") == 20
    qm.close()
    print("OK test_reset_all")


def test_status():
    qm = _qm()
    qm.ensure("a", total=100, quota_type="daily")
    qm.ensure("b", total=-1, quota_type="unlimited")
    qm.consume("a", amount=30)
    s = qm.status()
    assert len(s) == 2
    a = [x for x in s if x["provider"] == "a"][0]
    assert a["remaining"] == 70
    assert a["exhausted"] is False
    b = [x for x in s if x["provider"] == "b"][0]
    assert b["total"] == -1
    assert b["exhausted"] is False
    qm.close()
    print("OK test_status")


def test_log():
    qm = _qm()
    qm.ensure("p", total=10)
    qm.consume("p", amount=1, task_id="t1")
    qm.consume("p", amount=2, task_id="t2")
    logs = qm.log("p")
    assert len(logs) == 2
    assert logs[0]["amount"] == 2
    assert logs[1]["amount"] == 1
    qm.close()
    print("OK test_log")


def test_summary():
    qm = _qm()
    qm.ensure("p", total=50, quota_type="daily")
    qm.consume("p", amount=25)
    s = qm.summary()
    assert "p" in s
    qm.close()
    print("OK test_summary")


def test_persist():
    db = tempfile.mktemp(suffix=".db")
    try:
        qm1 = QuotaManager(db)
        qm1.ensure("p", total=100)
        qm1.consume("p", amount=40)
        qm1.close()
        qm2 = QuotaManager(db)
        assert qm2.remaining("p") == 60
        qm2.close()
    finally:
        os.unlink(db)
    print("OK test_persist")


if __name__ == "__main__":
    tests = [
        test_init, test_ensure, test_ensure_idempotent,
        test_consume, test_exhausted, test_unlimited,
        test_unregistered, test_reset_one, test_reset_all,
        test_status, test_log, test_summary, test_persist,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    print(f"\nQuota: {len(tests)-failed}/{len(tests)} passed")
    if failed:
        sys.exit(1)
