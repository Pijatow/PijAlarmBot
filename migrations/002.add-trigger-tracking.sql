-- step: apply
ALTER TABLE alerts ADD COLUMN trigger_count INTEGER DEFAULT 0;
ALTER TABLE alerts ADD COLUMN last_message_id INTEGER;

-- step: rollback
-- SQLite doesn't easily support dropping columns. The rollback is to recreate the table without the new columns.
PRAGMA foreign_keys=off;
BEGIN TRANSACTION;
CREATE TABLE alerts_new (
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
    trigger_count_today INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1
);
INSERT INTO alerts_new SELECT id, user_id, alert_description, alert_type, pair, timeframe, price, candle_slope, created_at, last_triggered, trigger_count_today, is_active FROM alerts;
DROP TABLE alerts;
ALTER TABLE alerts_new RENAME TO alerts;
COMMIT;
PRAGMA foreign_keys=on;