from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .types import UsageRecord


def _month_key(ts: datetime | None = None) -> str:
    value = ts or datetime.now(timezone.utc)
    return value.strftime("%Y-%m")


class UsageLedger:
    """SQLite-backed usage ledger for per-project budget checks."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    month_key TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    cost_usd REAL NOT NULL,
                    status_code INTEGER NOT NULL,
                    error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_usage_ledger_project_month
                ON usage_ledger(project_id, month_key)
                """
            )

    def current_month_spend(self, project_id: str) -> float:
        month_key = _month_key()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0.0) FROM usage_ledger WHERE project_id = ? AND month_key = ?",
                    (project_id, month_key),
                ).fetchone()
        return float(row[0] if row else 0.0)

    def record(self, usage: UsageRecord) -> None:
        now = datetime.now(timezone.utc)
        month_key = _month_key(now)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO usage_ledger (
                        created_at, month_key, request_id, project_id, endpoint, model,
                        prompt_tokens, completion_tokens, cost_usd, status_code, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now.isoformat(),
                        month_key,
                        usage.request_id,
                        usage.project_id,
                        usage.endpoint,
                        usage.model,
                        int(usage.prompt_tokens),
                        int(usage.completion_tokens),
                        float(usage.cost_usd),
                        int(usage.status_code),
                        usage.error,
                    ),
                )
