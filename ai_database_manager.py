import sqlite3
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime


class DatabaseManager:
    def __init__(self, db_file: str, ALLOWED_USERS):
        self.db_file = db_file
        self.ALLOWED_USERS = ALLOWED_USERS
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                alert_description TEXT,
                alert_type TEXT,
                pair TEXT,
                timeframe TEXT,
                price INTEGER,
                created_at TIMESTAMP,
                last_triggered TIMESTAMP,
                trigger_count_today INTEGER DEFAULT 0,
                message_id INTEGER,
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
                joined_at TIMESTAMP
            )
        """
        )

        conn.commit()
        conn.close()

    def add_user(self, user_id: int, username: str = None, first_name: str = None):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO users
            (user_id, username, first_name, is_allowed, joined_at)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                user_id,
                username,
                first_name,
                user_id in self.ALLOWED_USERS,
                datetime.now(),
            ),
        )

        conn.commit()
        conn.close()

    def save_alert(self, alert_data: Dict[str, Any]):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        if True:
            # Insert new alert
            cursor.execute(
                """
                INSERT INTO alerts
                (user_id, alert_description, alert_type, pair, timeframe,
                price, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    alert_data["user_id"],
                    alert_data["alert_description"],
                    alert_data["alert_type"],
                    alert_data["pair"],
                    alert_data["timeframe"],
                    alert_data["price"],
                    datetime.now(),
                ),
            )

        conn.commit()
        conn.close()

    def get_user_alerts(self, user_id: int, fields: List[str]) -> List[Dict]:
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute(
            f"""
            SELECT {", ".join(fields)} FROM alerts
            WHERE user_id = ? AND is_active = 1
            ORDER BY created_at DESC
        """,
            (user_id,),
        )
        result = []
        alerts = cursor.fetchall()
        for index, alert in enumerate(alerts):
            result.append({})
            for field, value in zip(fields, alert):
                result[index][field] = value
        conn.close()
        return result

    def get_alert_by_id(self, user_id: int, alert_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific alert by ID for a user."""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, user_id, alert_description, alert_type, pair,
                   timeframe, price, created_at, is_active
            FROM alerts
            WHERE user_id = ? AND id = ? AND is_active = 1
            """,
            (user_id, alert_id),
        )

        alert_data = cursor.fetchone()
        conn.close()

        if alert_data:
            fields = [
                "id",
                "user_id",
                "alert_description",
                "alert_type",
                "pair",
                "timeframe",
                "price",
                "created_at",
                "is_active",
            ]
            return dict(zip(fields, alert_data))
        return None

    def delete_user_alert(self, user_id: int, alert_id: int) -> Tuple[bool, str]:
        """
        Delete a user alert with improved error handling and verification.

        Returns:
            Tuple[bool, str]: (success_status, message)
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        try:
            # First check if alert exists and belongs to user
            cursor.execute(
                "SELECT id FROM alerts WHERE user_id = ? AND id = ? AND is_active = 1",
                (user_id, alert_id),
            )

            if not cursor.fetchone():
                conn.close()
                return False, "آلارم یافت نشد یا قبلاً حذف شده است."

            # Perform soft delete (mark as inactive)
            cursor.execute(
                "UPDATE alerts SET is_active = 0 WHERE user_id = ? AND id = ?",
                (user_id, alert_id),
            )

            if cursor.rowcount > 0:
                conn.commit()
                conn.close()
                return True, f"آلارم با شناسه {alert_id} با موفقیت حذف شد."
            else:
                conn.close()
                return False, "خطا در حذف آلارم."

        except sqlite3.Error as e:
            conn.close()
            return False, f"خطای دیتابیس: {str(e)}"

    def hard_delete_user_alert(self, user_id: int, alert_id: int) -> Tuple[bool, str]:
        """
        Permanently delete a user alert (hard delete).

        Returns:
            Tuple[bool, str]: (success_status, message)
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        try:
            # Check if alert exists and belongs to user
            cursor.execute(
                "SELECT id FROM alerts WHERE user_id = ? AND id = ?",
                (user_id, alert_id),
            )

            if not cursor.fetchone():
                conn.close()
                return False, "آلارم یافت نشد."

            # Perform hard delete
            cursor.execute(
                "DELETE FROM alerts WHERE user_id = ? AND id = ?",
                (user_id, alert_id),
            )

            if cursor.rowcount > 0:
                conn.commit()
                conn.close()
                return True, f"آلارم با شناسه {alert_id} به طور کامل حذف شد."
            else:
                conn.close()
                return False, "خطا در حذف آلارم."

        except sqlite3.Error as e:
            conn.close()
            return False, f"خطای دیتابیس: {str(e)}"

    def delete_all_user_alerts(self, user_id: int) -> Tuple[bool, str, int]:
        """
        Delete all alerts for a specific user.

        Returns:
            Tuple[bool, str, int]: (success_status, message, deleted_count)
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        try:
            # Count active alerts first
            cursor.execute(
                "SELECT COUNT(*) FROM alerts WHERE user_id = ? AND is_active = 1",
                (user_id,),
            )
            alert_count = cursor.fetchone()[0]

            if alert_count == 0:
                conn.close()
                return False, "هیچ آلارم فعالی برای حذف یافت نشد.", 0

            # Soft delete all user alerts
            cursor.execute(
                "UPDATE alerts SET is_active = 0 WHERE user_id = ? AND is_active = 1",
                (user_id,),
            )

            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()

            return True, f"{deleted_count} آلارم با موفقیت حذف شدند.", deleted_count

        except sqlite3.Error as e:
            conn.close()
            return False, f"خطای دیتابیس: {str(e)}", 0

    def get_alert_count(self, user_id: int) -> int:
        """Get the count of active alerts for a user."""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM alerts WHERE user_id = ? AND is_active = 1",
            (user_id,),
        )

        count = cursor.fetchone()[0]
        conn.close()
        return count

    def restore_user_alert(self, user_id: int, alert_id: int) -> Tuple[bool, str]:
        """
        Restore a soft-deleted alert.

        Returns:
            Tuple[bool, str]: (success_status, message)
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        try:
            # Check if alert exists and is inactive
            cursor.execute(
                "SELECT id FROM alerts WHERE user_id = ? AND id = ? AND is_active = 0",
                (user_id, alert_id),
            )

            if not cursor.fetchone():
                conn.close()
                return False, "آلارم یافت نشد یا قبلاً فعال است."

            # Restore the alert
            cursor.execute(
                "UPDATE alerts SET is_active = 1 WHERE user_id = ? AND id = ?",
                (user_id, alert_id),
            )

            if cursor.rowcount > 0:
                conn.commit()
                conn.close()
                return True, f"آلارم با شناسه {alert_id} بازیابی شد."
            else:
                conn.close()
                return False, "خطا در بازیابی آلارم."

        except sqlite3.Error as e:
            conn.close()
            return False, f"خطای دیتابیس: {str(e)}"
