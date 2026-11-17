import json
import sqlite3
from datetime import timedelta
from pathlib import Path

from .models import Metrics


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=20)
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 2:
            self.db.close()
            raise ValueError("数据库版本较新，请升级程序")
        if version == 0:
            self.db.executescript("""
                CREATE TABLE metrics (
                    site TEXT, source TEXT, scope TEXT, start TEXT, end TEXT,
                    payload TEXT NOT NULL, assessment TEXT NOT NULL,
                    PRIMARY KEY (site, source, scope, start, end)
                );
                CREATE TABLE runs (
                    id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL, detail TEXT NOT NULL
                );
                CREATE TABLE notifications (
                    key TEXT PRIMARY KEY, status TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                PRAGMA user_version = 1;
            """)
        if version < 2:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS scheduled_runs (
                    key TEXT PRIMARY KEY, planned TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 1,
                    started TEXT NOT NULL, finished TEXT, detail TEXT, report TEXT
                );
                CREATE TABLE IF NOT EXISTS tracking (
                    id TEXT PRIMARY KEY, started TEXT NOT NULL
                );
                PRAGMA user_version = 2;
            """)

    def close(self):
        self.db.close()

    def save(self, metrics, assessment):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (metrics.site_id, metrics.source, metrics.scope, metrics.start.isoformat(),
                             metrics.end.isoformat(), json.dumps(metrics.to_dict(), ensure_ascii=False), assessment.status))

    def baseline(self, metrics, rules):
        if metrics.window_kind == "relative":
            # Rolling snapshots overlap and are not aligned historical hours.
            return None
        rows = self.db.execute("SELECT payload FROM metrics WHERE site=? AND source=? AND scope=?",
                               (metrics.site_id, metrics.source, metrics.scope)).fetchall()
        samples = []
        for (payload,) in rows:
            old = Metrics.from_dict(json.loads(payload))
            age = metrics.start - old.start
            if (timedelta(0) < age <= timedelta(days=rules["history_days"])
                    and old.start.hour == metrics.start.hour and old.start.minute == metrics.start.minute
                    and old.end - old.start == metrics.end - metrics.start
                    and old.start.weekday() < 5 and metrics.start.weekday() < 5
                    and old.total >= rules["min_requests"]):
                samples.append(old)
        return sum(m.success for m in samples) / sum(m.total for m in samples) if samples else None

    def record_run(self, status, detail):
        with self.db:
            self.db.execute("INSERT INTO runs(status, detail) VALUES (?, ?)", (status, detail))

    def was_sent(self, key):
        row = self.db.execute("SELECT status FROM notifications WHERE key=?", (key,)).fetchone()
        return row is not None and row[0] == "sent"

    def notification(self, key, status):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO notifications(key, status) VALUES (?, ?)", (key, status))

    def claim_slot(self, key, planned, now):
        """Atomic claim; stale processes can be reclaimed after OS five-minute limit."""
        from datetime import datetime
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT status, started FROM scheduled_runs WHERE key=?", (key,)).fetchone()
            if row:
                if row[0] == "sent" or (row[0] == "running" and now - datetime.fromisoformat(row[1]) < timedelta(minutes=5)):
                    return False
                self.db.execute("UPDATE scheduled_runs SET status='running', started=?, finished=NULL, attempts=attempts+1 WHERE key=?",
                                (now.isoformat(), key))
            else:
                self.db.execute("INSERT INTO scheduled_runs(key, planned, status, started) VALUES (?, ?, 'running', ?)",
                                (key, planned.isoformat(), now.isoformat()))
            return True

    def finish_slot(self, key, status, now, detail):
        with self.db:
            self.db.execute("UPDATE scheduled_runs SET status=?, finished=?, detail=? WHERE key=?",
                            (status, now.isoformat(), detail, key))

    def pending_report(self, key):
        row = self.db.execute("SELECT report FROM scheduled_runs WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def save_report(self, key, report):
        with self.db:
            self.db.execute("UPDATE scheduled_runs SET report=? WHERE key=?", (report, key))
