from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


TERMINAL_STATUSES = {"WIN", "LOSS", "EXPIRED", "INVALID", "WATCH"}
OPEN_STATUSES = {"PENDING", "TRIGGERED"}


def default_signal_db_target() -> str:
    """Use PostgreSQL in production while keeping local/test startup friction low."""
    database_url = os.getenv("DATABASE_URL") or os.getenv("MONATISE_DATABASE_URL")
    if database_url:
        return database_url
    auth_db = os.getenv("MONATISE_AUTH_DB")
    if auth_db:
        return auth_db
    if Path("/data").exists():
        return "/data/monatise-users.db"
    return str(Path(__file__).resolve().parents[2] / "work" / "monatise-users.db")


@dataclass(frozen=True)
class SignalRecord:
    id: str
    symbol: str
    interval: str
    direction: str
    source: str
    entry: float | None
    stop: float | None
    target_one: float | None
    target_two: float | None
    confidence: float | None
    setup_grade: str
    status: str
    created_at: float
    expires_at: float | None
    triggered_at: float | None
    resolved_at: float | None
    mfe_pct: float | None
    mae_pct: float | None
    return_r: float | None
    outcome_detail: str
    evidence: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        result = asdict(self)
        result.update(
            {
                "targetOne": result.pop("target_one"),
                "targetTwo": result.pop("target_two"),
                "setupGrade": result.pop("setup_grade"),
                "createdAt": result.pop("created_at"),
                "expiresAt": result.pop("expires_at"),
                "triggeredAt": result.pop("triggered_at"),
                "resolvedAt": result.pop("resolved_at"),
                "mfePct": result.pop("mfe_pct"),
                "maePct": result.pop("mae_pct"),
                "returnR": result.pop("return_r"),
                "outcomeDetail": result.pop("outcome_detail"),
            }
        )
        return result


class SignalPerformanceStore:
    """Durable signal ledger supporting PostgreSQL and a local SQLite bridge.

    SQLite remains only so existing Render authentication data can be migrated
    without an unsafe flag day. Setting DATABASE_URL selects PostgreSQL.
    """

    def __init__(self, target: str | None = None) -> None:
        self.target = target or default_signal_db_target()
        self.postgres = self.target.startswith(("postgres://", "postgresql://"))
        if not self.postgres:
            Path(self.target).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @property
    def backend(self) -> str:
        return "postgresql" if self.postgres else "sqlite-migration-bridge"

    def save(self, payload: dict[str, Any], user_id: int | None = None) -> SignalRecord:
        record = self._normalize(payload)
        params = (
            record.id,
            user_id,
            record.symbol,
            record.interval,
            record.direction,
            record.source,
            record.entry,
            record.stop,
            record.target_one,
            record.target_two,
            record.confidence,
            record.setup_grade,
            record.status,
            record.created_at,
            record.expires_at,
            record.triggered_at,
            record.resolved_at,
            record.mfe_pct,
            record.mae_pct,
            record.return_r,
            record.outcome_detail,
            json.dumps(record.evidence, separators=(",", ":")),
            time.time(),
        )
        query = """
            insert into signal_records(
              id, user_id, symbol, interval, direction, source, entry, stop,
              target_one, target_two, confidence, setup_grade, status, created_at,
              expires_at, triggered_at, resolved_at, mfe_pct, mae_pct, return_r,
              outcome_detail, evidence_json, updated_at
            ) values ({placeholders})
            on conflict(id) do update set
              status=excluded.status, triggered_at=excluded.triggered_at,
              resolved_at=excluded.resolved_at, mfe_pct=excluded.mfe_pct,
              mae_pct=excluded.mae_pct, return_r=excluded.return_r,
              outcome_detail=excluded.outcome_detail,
              evidence_json=excluded.evidence_json, updated_at=excluded.updated_at
        """.format(placeholders=", ".join([self._placeholder] * len(params)))
        with self._connect() as conn:
            conn.execute(query, params)
        return record

    def records(self, user_id: int | None = None, limit: int = 200) -> list[SignalRecord]:
        limit = min(max(int(limit), 1), 1000)
        where = "where user_id is null" if user_id is None else f"where user_id = {self._placeholder}"
        params: tuple[Any, ...] = () if user_id is None else (user_id,)
        with self._connect() as conn:
            rows = conn.execute(
                f"select * from signal_records {where} order by created_at desc limit {limit}", params
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def summary(self, user_id: int | None = None) -> dict[str, Any]:
        records = self.records(user_id=user_id, limit=1000)
        resolved = [record for record in records if record.status in {"WIN", "LOSS"}]
        wins = sum(record.status == "WIN" for record in resolved)
        losses = sum(record.status == "LOSS" for record in resolved)
        returns = [record.return_r for record in resolved if record.return_r is not None]
        cumulative_r = 0.0
        peak_r = 0.0
        max_drawdown_r = 0.0
        for record in sorted(resolved, key=lambda item: item.created_at):
            cumulative_r += record.return_r or 0.0
            peak_r = max(peak_r, cumulative_r)
            max_drawdown_r = max(max_drawdown_r, peak_r - cumulative_r)
        groups: dict[str, dict[str, Any]] = {}
        for record in records:
            key = f"{record.symbol}:{record.interval}"
            group = groups.setdefault(key, {"symbol": record.symbol, "interval": record.interval, "tracked": 0, "wins": 0, "losses": 0})
            group["tracked"] += 1
            group["wins"] += int(record.status == "WIN")
            group["losses"] += int(record.status == "LOSS")
        for group in groups.values():
            decided = group["wins"] + group["losses"]
            group["winRate"] = round(group["wins"] / decided * 100, 2) if decided else None
        return {
            "backend": self.backend,
            "tracked": len(records),
            "open": sum(record.status in OPEN_STATUSES for record in records),
            "wins": wins,
            "losses": losses,
            "decided": len(resolved),
            "winRate": round(wins / len(resolved) * 100, 2) if resolved else None,
            "expectancyR": round(sum(returns) / len(returns), 3) if returns else None,
            "netR": round(sum(returns), 3) if returns else None,
            "maxDrawdownR": round(max_drawdown_r, 3) if returns else None,
            "byMarket": sorted(groups.values(), key=lambda item: (-item["tracked"], item["symbol"])),
        }

    @property
    def _placeholder(self) -> str:
        return "%s" if self.postgres else "?"

    def _connect(self):  # noqa: ANN202
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row

            return psycopg.connect(self.target, row_factory=dict_row)
        conn = sqlite3.connect(self.target)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        id_column = "bigint" if self.postgres else "integer"
        schema = f"""
            create table if not exists signal_records(
              id text primary key,
              user_id {id_column},
              symbol text not null,
              interval text not null,
              direction text not null,
              source text not null,
              entry double precision,
              stop double precision,
              target_one double precision,
              target_two double precision,
              confidence double precision,
              setup_grade text not null,
              status text not null,
              created_at double precision not null,
              expires_at double precision,
              triggered_at double precision,
              resolved_at double precision,
              mfe_pct double precision,
              mae_pct double precision,
              return_r double precision,
              outcome_detail text not null,
              evidence_json text not null,
              updated_at double precision not null
            )
        """
        with self._connect() as conn:
            conn.execute(schema)
            conn.execute("create index if not exists signal_records_market_idx on signal_records(symbol, interval, created_at)")
            conn.execute("create index if not exists signal_records_status_idx on signal_records(status, created_at)")

    @staticmethod
    def _timestamp(value: Any) -> float | None:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            numeric = float(value)
            return numeric / 1000 if numeric > 10_000_000_000 else numeric
        from datetime import datetime

        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()

    def _normalize(self, payload: dict[str, Any]) -> SignalRecord:
        status = str(payload.get("status") or "PENDING").upper()
        if status not in TERMINAL_STATUSES | OPEN_STATUSES:
            status = "PENDING"
        direction = str(payload.get("direction") or "WATCH").upper()
        if direction not in {"LONG", "SHORT", "WATCH"}:
            raise ValueError("signal direction must be LONG, SHORT, or WATCH")
        created_at = self._timestamp(payload.get("createdAt")) or time.time()
        return SignalRecord(
            id=str(payload.get("id") or uuid.uuid4()),
            symbol=str(payload.get("symbol") or "").upper()[:24],
            interval=str(payload.get("interval") or "unknown")[:16],
            direction=direction,
            source=str(payload.get("source") or "monatise")[:64],
            entry=self._number(payload.get("entry")),
            stop=self._number(payload.get("stop")),
            target_one=self._number(payload.get("targetOne")),
            target_two=self._number(payload.get("targetTwo")),
            confidence=self._number(payload.get("confidence")),
            setup_grade=str(payload.get("setupGrade") or "Watch")[:16],
            status=status,
            created_at=created_at,
            expires_at=self._timestamp(payload.get("expiresAt")),
            triggered_at=self._timestamp(payload.get("triggeredAt")),
            resolved_at=self._timestamp(payload.get("resolvedAt")),
            mfe_pct=self._number(payload.get("mfePct")),
            mae_pct=self._number(payload.get("maePct")),
            return_r=self._number(payload.get("returnR")) or self._derived_return_r(payload, status),
            outcome_detail=str(payload.get("outcomeDetail") or "")[:500],
            evidence=dict(payload.get("evidence") or {}),
        )

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            number = float(value)
            return number if number == number else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _derived_return_r(cls, payload: dict[str, Any], status: str) -> float | None:
        entry, stop, target = (cls._number(payload.get(key)) for key in ("entry", "stop", "targetOne"))
        risk = abs(entry - stop) if entry is not None and stop is not None else 0
        if status == "LOSS":
            return -1.0
        if status == "WIN" and entry is not None and target is not None and risk > 0:
            return round(abs(target - entry) / risk, 4)
        return None

    @staticmethod
    def _from_row(row: Any) -> SignalRecord:
        return SignalRecord(
            id=str(row["id"]), symbol=str(row["symbol"]), interval=str(row["interval"]),
            direction=str(row["direction"]), source=str(row["source"]), entry=row["entry"],
            stop=row["stop"], target_one=row["target_one"], target_two=row["target_two"],
            confidence=row["confidence"], setup_grade=str(row["setup_grade"]), status=str(row["status"]),
            created_at=float(row["created_at"]), expires_at=row["expires_at"], triggered_at=row["triggered_at"],
            resolved_at=row["resolved_at"], mfe_pct=row["mfe_pct"], mae_pct=row["mae_pct"],
            return_r=row["return_r"], outcome_detail=str(row["outcome_detail"]),
            evidence=json.loads(row["evidence_json"] or "{}"),
        )


def import_signal_records(store: SignalPerformanceStore, records: Iterable[dict[str, Any]], user_id: int | None = None) -> int:
    count = 0
    for record in records:
        store.save(record, user_id=user_id)
        count += 1
    return count
