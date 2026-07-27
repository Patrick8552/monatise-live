from __future__ import annotations

from monatise.live.performance import SignalPerformanceStore


def signal_payload(identifier: str, status: str, *, symbol: str = "BTC") -> dict:
    return {
        "id": identifier,
        "symbol": symbol,
        "interval": "1h",
        "direction": "LONG",
        "source": "test",
        "entry": 100,
        "stop": 95,
        "targetOne": 110,
        "confidence": 72,
        "setupGrade": "B",
        "status": status,
        "createdAt": "2026-07-27T10:00:00Z",
        "outcomeDetail": "test outcome",
        "evidence": {"feed": "fixture"},
    }


def test_signal_ledger_upserts_and_summarizes_outcomes(tmp_path) -> None:
    store = SignalPerformanceStore(str(tmp_path / "signals.db"))
    store.save(signal_payload("one", "PENDING"), user_id=7)
    store.save(signal_payload("one", "WIN"), user_id=7)
    store.save(signal_payload("two", "LOSS", symbol="ETH"), user_id=7)

    records = store.records(user_id=7)
    summary = store.summary(user_id=7)

    assert len(records) == 2
    assert {record.status for record in records} == {"WIN", "LOSS"}
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["winRate"] == 50.0
    assert summary["expectancyR"] == 0.5
    assert summary["backend"] == "sqlite-migration-bridge"


def test_signal_ledger_isolated_by_user(tmp_path) -> None:
    store = SignalPerformanceStore(str(tmp_path / "signals.db"))
    store.save(signal_payload("user-one", "WIN"), user_id=1)
    store.save(signal_payload("user-two", "LOSS"), user_id=2)

    assert [record.id for record in store.records(user_id=1)] == ["user-one"]
    assert [record.id for record in store.records(user_id=2)] == ["user-two"]
