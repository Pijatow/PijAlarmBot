import sqlite3
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

# A list of columns that are safe to be queried directly.
# This is a security measure to prevent SQL injection.
ALLOWED_QUERY_FIELDS = [
    "id",
    "user_id",
    "alert_description",
    "alert_type",
    "pair",
    "timeframe",
    "price",
    "created_at",
    "is_active",
    "candle_slope",
    "trigger_count",
    "last_message_id",
]


class DatabaseManager:
    def __init__(self, db_file: str):
        self.db_file = db_file
        self.init_db()

    def _get_connection(self):
        """Creates and returns a new database connection."""
        return sqlite3.connect(self.db_file)

    def init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    alert_description TEXT,
                    alert_type TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    timeframe TEXT,
                    price REAL NOT NULL,
                    candle_slope TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_triggered TIMESTAMP,
                    trigger_count INTEGER DEFAULT 0,
                    last_message_id INTEGER,
                    is_active BOOLEAN DEFAULT 1
                )
            """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    is_allowed BOOLEAN DEFAULT 0,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )
            conn.commit()

    def add_user(
        self, user_id: int, username: str, first_name: str, is_allowed: bool
    ):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO users (user_id, username, first_name, is_allowed, joined_at)
                VALUES (?, ?, ?, ?, ?)
            """,
                (user_id, username, first_name, is_allowed, datetime.now()),
            )
            conn.commit()

    def save_alert(self, alert_data: Dict[str, Any]) -> Optional[int]:
        # Basic validation to ensure required fields are present
        required_fields = ["user_id", "alert_type", "pair", "price"]
        if not all(field in alert_data for field in required_fields):
            print("Error: Missing required fields in alert_data")
            return None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO alerts
                (user_id, alert_description, alert_type, pair, timeframe, price, candle_slope, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    alert_data.get("user_id"),
                    alert_data.get("alert_description"),
                    alert_data.get("alert_type"),
                    alert_data.get("pair"),
                    alert_data.get("timeframe"),
                    alert_data.get("price"),
                    alert_data.get("candle_slope"),  # Safely get candle_slope
                    datetime.now(),
                ),
            )
            conn.commit()
            return cursor.lastrowid  # Return the ID of the new alert

    def update_alert_trigger_info(
        self, alert_id: int, message_id: int
    ):
        """Increments the trigger count and updates the last message ID for an alert."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE alerts
                SET trigger_count = trigger_count + 1,
                    last_message_id = ?,
                    last_triggered = ?
                WHERE id = ?
                """,
                (message_id, datetime.now(), alert_id),
            )
            conn.commit()

    def get_user_alerts(self, user_id: int, fields: List[str]) -> List[Dict]:
        # --- SQL Injection Prevention ---
        # Validate every field against a whitelist before building the query.
        for field in fields:
            if field not in ALLOWED_QUERY_FIELDS:
                raise ValueError(f"Disallowed field in query: {field}")

        query = f"""
            SELECT {", ".join(fields)} FROM alerts
            WHERE user_id = ? AND is_active = 1
            ORDER BY created_at DESC
        """
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row  # Makes rows accessible by column name
            cursor = conn.cursor()
            cursor.execute(query, (user_id,))
            # Convert rows to dictionaries for easier use
            return [dict(row) for row in cursor.fetchall()]

    def get_all_active_alerts(self) -> List[Dict]:
        """Fetches all active alerts from the database, used for persistence on restart."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM alerts WHERE is_active = 1")
            return [dict(row) for row in cursor.fetchall()]

    def get_alert_by_id(self, user_id: int, alert_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM alerts WHERE user_id = ? AND id = ?",
                (user_id, alert_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_user_alert(self, user_id: int, alert_id: int) -> Tuple[bool, str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE alerts SET is_active = 0 WHERE user_id = ? AND id = ?",
                (user_id, alert_id),
            )
            conn.commit()
            if cursor.rowcount > 0:
                return True, f"آلارم با شناسه {alert_id} با موفقیت حذف شد."
            return False, "آلارم یافت نشد یا قبلاً حذف شده است."

    def delete_all_user_alerts(self, user_id: int) -> Tuple[bool, str, int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE alerts SET is_active = 0 WHERE user_id = ? AND is_active = 1",
                (user_id,),
            )
            deleted_count = cursor.rowcount
            conn.commit()
            if deleted_count > 0:
                return (
                    True,
                    f"{deleted_count} آلارم با موفقیت حذف شدند.",
                    deleted_count,
                )
            return False, "هیچ آلارم فعالی برای حذف یافت نشد.", 0

    def get_alert_count(self, user_id: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM alerts WHERE user_id = ? AND is_active = 1",
                (user_id,),
            )
            return cursor.fetchone()[0]