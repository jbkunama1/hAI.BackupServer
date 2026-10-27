"""SQLite-Speicher fuer Laeufe, Ereignisse, Audit-Log (transaktional, WAL)."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

FINAL = ("ok", "warning", "error")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, host_id TEXT NOT NULL, status TEXT NOT NULL,
  exit_code INTEGER NOT NULL DEFAULT 0, started_at TEXT, finished_at TEXT,
  first_seen_at TEXT NOT NULL, reported_at TEXT NOT NULL,
  duration_seconds REAL NOT NULL DEFAULT 0, size_bytes INTEGER NOT NULL DEFAULT 0,
  warnings INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '', final INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_runs_host ON runs(host_id, first_seen_at);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, host_id TEXT NOT NULL,
  run_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(type, run_id));
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL,
  action TEXT NOT NULL, target TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class Store:
    def __init__(self, path):
        self.path = str(path)
        c = self._connect()
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
        finally:
            c.close()

    def _connect(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        return c

    @contextmanager
    def tx(self):
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except BaseException:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            c.close()

    def _all(self, sql, args=()):
        c = self._connect()
        try:
            return [dict(r) for r in c.execute(sql, args).fetchall()]
        finally:
            c.close()

    def upsert_run(self, host_id, data, history_limit=200, now=None, host_name=""):
        """Legt einen Lauf an/aktualisiert ihn. Rueckgabe: (run, neuer_fehler)."""
        now = now or now_iso()
        rid, status = data["run_id"], data["status"]
        with self.tx() as c:
            row = c.execute("SELECT * FROM runs WHERE run_id=?", (rid,)).fetchone()
            if row and row["host_id"] != host_id:
                raise ValueError("run_id gehoert zu einem anderen Host")
            if row and row["final"] and status == "running":
                return dict(row), False          # verspaetetes Start-Signal ignorieren
            final = 1 if status in FINAL else 0
            vals = (status, int(data.get("exit_code", 0)), data.get("started_at"),
                    now if final else None, now, float(data.get("duration_seconds", 0)),
                    int(data.get("size_bytes", 0)), int(data.get("warnings", 0)),
                    str(data.get("message", ""))[:2000], final)
            if row:
                c.execute("UPDATE runs SET status=?, exit_code=?, started_at=COALESCE(?, started_at), "
                          "finished_at=?, reported_at=?, duration_seconds=?, size_bytes=?, warnings=?, "
                          "message=?, final=? WHERE run_id=?", vals + (rid,))
            else:
                c.execute("INSERT INTO runs(status, exit_code, started_at, finished_at, reported_at, "
                          "duration_seconds, size_bytes, warnings, message, final, run_id, host_id, "
                          "first_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          vals + (rid, host_id, now))
            new_error = False
            if status == "error":
                payload = json.dumps({"host_name": host_name, "exit_code": vals[1],
                                      "message": vals[8], "duration_seconds": vals[5]})
                cur = c.execute("INSERT OR IGNORE INTO events(type, host_id, run_id, payload, created_at) "
                                "VALUES ('run_error',?,?,?,?)", (host_id, rid, payload, now))
                new_error = cur.rowcount == 1
            c.execute("DELETE FROM runs WHERE host_id=? AND run_id NOT IN (SELECT run_id FROM runs "
                      "WHERE host_id=? ORDER BY first_seen_at DESC, rowid DESC LIMIT ?)",
                      (host_id, host_id, int(history_limit)))
            return dict(c.execute("SELECT * FROM runs WHERE run_id=?", (rid,)).fetchone()), new_error

    def last_run(self, host_id):
        r = self._all("SELECT * FROM runs WHERE host_id=? ORDER BY first_seen_at DESC, rowid DESC LIMIT 1",
                      (host_id,))
        return r[0] if r else None

    def last_success(self, host_id):
        r = self._all("SELECT * FROM runs WHERE host_id=? AND status IN ('ok','warning') "
                      "ORDER BY first_seen_at DESC, rowid DESC LIMIT 1", (host_id,))
        return r[0] if r else None

    def latest_per_host(self):
        rows = self._all("SELECT * FROM runs r WHERE rowid = (SELECT rowid FROM runs WHERE host_id=r.host_id "
                         "ORDER BY first_seen_at DESC, rowid DESC LIMIT 1)")
        return {r["host_id"]: r for r in rows}

    def list_runs(self, host_id=None, limit=50):
        limit = max(1, min(int(limit), 500))
        if host_id:
            return self._all("SELECT * FROM runs WHERE host_id=? ORDER BY first_seen_at DESC, rowid DESC LIMIT ?",
                             (host_id, limit))
        return self._all("SELECT * FROM runs ORDER BY first_seen_at DESC, rowid DESC LIMIT ?", (limit,))

    def events_after(self, after_id=0, types=("run_error",), limit=100):
        marks = ",".join("?" for _ in types)
        rows = self._all(f"SELECT * FROM events WHERE id>? AND type IN ({marks}) ORDER BY id LIMIT ?",
                         (int(after_id), *types, int(limit)))
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows

    def audit(self, actor, action, target="", detail=""):
        with self.tx() as c:
            c.execute("INSERT INTO audit(ts, actor, action, target, detail) VALUES (?,?,?,?,?)",
                      (now_iso(), str(actor)[:100], action, str(target)[:100], str(detail)[:500]))

    def list_audit(self, limit=50):
        return self._all("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (int(limit),))

    def meta_get(self, key, default=None):
        r = self._all("SELECT v FROM meta WHERE k=?", (key,))
        return r[0]["v"] if r else default

    def meta_set(self, key, value):
        with self.tx() as c:
            c.execute("INSERT INTO meta(k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                      (key, str(value)))

    def import_legacy_reports(self, path):
        """Uebernimmt die alte reports.json einmalig (Original bleibt unveraendert)."""
        if self.meta_get("legacy_reports_imported"):
            return 0
        n = 0
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return 0
        for host_id, rep in (data.get("reports") or {}).items():
            try:
                status = rep["status"] if rep.get("status") in FINAL else None
                if not status:
                    continue
                stamp = "".join(ch for ch in str(rep.get("reported_at", "")) if ch.isdigit()) or "0"
                self.upsert_run(str(host_id), {
                    "run_id": f"legacy-{host_id}-{stamp}"[:64], "status": status,
                    "exit_code": rep.get("exit_code", 0), "duration_seconds": rep.get("duration_seconds", 0),
                    "size_bytes": rep.get("size_bytes", 0), "message": rep.get("message", "")},
                    now=rep.get("reported_at") or now_iso())
                n += 1
            except (KeyError, ValueError, TypeError):
                continue
        self.meta_set("legacy_reports_imported", now_iso())
        return n
