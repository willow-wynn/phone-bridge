import sqlite3
from datetime import datetime, timezone


class SessionStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    phone_number TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    working_dir TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    last_used_at TEXT DEFAULT (datetime('now')),
                    message_count INTEGER DEFAULT 0,
                    total_cost_usd REAL DEFAULT 0.0
                )
            """)
            # Migrate existing tables that lack the cost column
            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN total_cost_usd REAL DEFAULT 0.0")
            except Exception:
                pass  # Column already exists

    def get_session(self, phone_number: str) -> str | None:
        """Return session_id for phone, or None if no session exists."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT session_id FROM sessions WHERE phone_number = ?",
                (phone_number,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE sessions SET last_used_at = ? WHERE phone_number = ?",
                    (datetime.now(timezone.utc).isoformat(), phone_number),
                )
                return row[0]
            return None

    def save_session(self, phone_number: str, session_id: str, working_dir: str, cost_usd: float = 0.0):
        """Upsert session_id for phone number, accumulating cost."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (phone_number, session_id, working_dir, created_at, last_used_at, message_count, total_cost_usd)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(phone_number) DO UPDATE SET
                    session_id = excluded.session_id,
                    last_used_at = excluded.last_used_at,
                    message_count = message_count + 1,
                    total_cost_usd = total_cost_usd + ?
                """,
                (phone_number, session_id, working_dir, now, now, cost_usd, cost_usd),
            )

    def get_cost(self, phone_number: str) -> float:
        """Return cumulative cost for a user."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT total_cost_usd FROM sessions WHERE phone_number = ?",
                (phone_number,),
            ).fetchone()
            return row[0] if row else 0.0

    def reset_session(self, phone_number: str):
        """Delete session for phone number."""
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE phone_number = ?", (phone_number,))

    def list_sessions(self) -> list[dict]:
        """Return all active sessions."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM sessions ORDER BY last_used_at DESC").fetchall()
            return [dict(row) for row in rows]
