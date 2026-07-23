"""SQLite Database Manager for Dreamer V2 runtime tracking."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import ArtifactState, ArtifactStatus


class DatabaseManager:
    """Manages local project state and cost ledger via SQLite."""

    def __init__(self, db_path: Path) -> None:
        """Initialize the database manager and create tables if not exists."""
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create necessary tables."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    path TEXT,
                    content_hash TEXT,
                    error TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cost_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    model TEXT NOT NULL,
                    tokens_input INTEGER DEFAULT 0,
                    tokens_output INTEGER DEFAULT 0,
                    images_count INTEGER DEFAULT 0,
                    resolution TEXT,
                    cost_usd REAL NOT NULL
                )
            """)
            conn.commit()

    def get_artifact(self, artifact_id: str) -> ArtifactState | None:
        """Retrieve artifact state from the database."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            if row:
                return ArtifactState(
                    artifact_id=row["artifact_id"],
                    status=ArtifactStatus(row["status"]),
                    path=row["path"],
                    content_hash=row["content_hash"],
                    error=row["error"],
                )
            return None

    def upsert_artifact(self, state: ArtifactState) -> None:
        """Insert or update artifact state."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (artifact_id, status, path, content_hash, error)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    status=excluded.status,
                    path=excluded.path,
                    content_hash=excluded.content_hash,
                    error=excluded.error
                """,
                (
                    state.artifact_id,
                    state.status.value,
                    state.path,
                    state.content_hash,
                    state.error,
                ),
            )
            conn.commit()

    def record_cost(
        self,
        phase: str,
        model: str,
        tokens_input: int = 0,
        tokens_output: int = 0,
        images_count: int = 0,
        resolution: str | None = None,
        cost_usd: float = 0.0,
    ) -> None:
        """Record an API cost event to the ledger."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO cost_ledger (timestamp, phase, model, tokens_input, tokens_output, images_count, resolution, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(UTC).isoformat(),
                    phase,
                    model,
                    tokens_input,
                    tokens_output,
                    images_count,
                    resolution,
                    cost_usd,
                ),
            )
            conn.commit()

    def get_total_cost(self) -> float:
        """Get the total accumulated cost in USD."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT SUM(cost_usd) as total FROM cost_ledger").fetchone()
            if row and row["total"] is not None:
                return float(row["total"])
            return 0.0
