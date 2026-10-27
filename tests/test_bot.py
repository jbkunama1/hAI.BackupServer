import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "telegram_bot"))
import bot as B  # noqa: E402


class FakeTg:
    def __init__(self):
        self.calls, self.fail = [], False

    def call(self, method, timeout=15, **p):
        if self.fail and method == "sendMessage":
            raise B.TgError("netz")
        self.calls.append((method, p))
        return True

    def sent(self):
        return [p for m, p in self.calls if m == "sendMessage"]


class FakeApi:
    def __init__(self):
        self.down, self.posts, self.events = False, [], []
        self.status = {"counts": {"ok": 1, "no_report": 1}, "hosts": [
            {"host_id": "5", "host_name": "h<5>", "state": "ok", "label": "OK", "overdue": False, "detail": "",
             "paused": False, "last": {"run_id": "r1", "size_bytes": 2048, "duration_seconds": 12, "first_seen_at": "2026-10-27T01:00:00Z", "message": "ok"},
             "last_success_at": "x"},
            {"host_id": "9", "host_name": "stumm", "state": "no_report", "label": "x", "overdue": False, "detail": "Noch keine Meldung", "paused": False, "last": None, "last_success_at": None}]}

    def get(self, path, params=None, actor="telegram:bot"):
        if self.down:
            raise B.ApiError("down")
        if path == "/api/status":
            return self.status
        if path == "/api/events":
            return {"events": [e for e in self.events if e["id"] > params["after"]]}
        if path == "/api/digest":
            return dict(self.status, hours=24, runs_in_window=3, attention=[self.status["hosts"][1]])
        if path == "/api/health":
            return {"status": "ok", "version": "2"}
        if path == "/api/runs":
            return {"runs": []}

    def post(self, path, json=None, actor="telegram:bot"):
        if self.down:
            raise B.ApiError("down")
        self.posts.append((path, json, actor))
        return {"status": "ok"}


@pytest.fixture
def bot(tmp_path):
    tg, api = FakeTg(), FakeApi()
    return B.Bot(tg, api, B.State(tmp_path / "s.db"), [111], "Europe/Berlin", "08:00"), tg, api


def cb(uid, data, chat="private"):
    return {"update_id": 1, "callback_query": {"id": "c", "from": {"id": uid}, "data": data,
            "message": {"message_id": 5, "chat": {"id": uid, "type": chat}}}}


def msg(uid, text, chat="private"):
    return {"update_id": 1, "message": {"from": {"id": uid}, "chat": {"id": uid, "type": chat}, "text": text}}


def test_default_deny_for_messages_and_buttons(bot):
    b, tg, api = bot
    b.handle_update(msg(999, "/admin"))
    b.handle_update(msg(111, "/admin", chat="group"))
    b.handle_update(cb(999, "pay:5:1"))
    b.handle_update(cb(111, "pay:5:1", chat="supergroup"))
    assert tg.sent() == [] and api.posts == []
    assert any(c[0] == "answerCallbackQuery" and c[1].get("show_alert") for c in tg.calls)


def test_menu_and_confirmation_before_mutation(bot):
    b, tg, api = bot
    b.handle_update(msg(111, "/admin"))
    assert tg.sent() and "inline_keyboard" in tg.sent()[0]["reply_markup"]
    b.handle_update(cb(111, "pa:5:1"))
    assert api.posts == []                                   # nur Rueckfrage
    b.handle_update(cb(111, "pay:5:1"))
    assert api.posts == [("/api/hosts/5/pause", {"paused": True}, "telegram:111")]
    b.handle_update(cb(111, "rgy:5"))
    assert api.posts[-1][0] == "/api/hosts/5/regenerate" and api.posts[-1][2] == "telegram:111"


def test_invalid_host_id_in_callback_is_ignored(bot):
    b, tg, api = bot
    b.handle_update(cb(111, "rgy:../../etc"))
    b.handle_update(cb(111, "pay:5/x:1"))
    assert api.posts == []


def test_errors_are_pushed_once_and_cursor_advances_only_on_success(bot):
    b, tg, api = bot
    api.events = [{"id": 1, "host_id": "5", "created_at": "t", "payload": {"host_name": "h", "exit_code": 2, "message": "<b>boom</b>"}}]
    tg.fail = True
    b.tick()
    assert b.state.get("event_cursor", "0") == "0"           # nicht verloren
    tg.fail = False
    b.tick(); b.tick()
    assert b.state.get("event_cursor") == "1"
    errs = [m for m in tg.sent() if "Backup-Fehler" in m["text"]]
    assert len(errs) == 1 and "&lt;b&gt;boom" in errs[0]["text"]       # HTML escaped, kein Duplikat


def test_daily_digest_once_survives_restart_and_names_silent_hosts(bot, tmp_path):
    b, tg, api = bot
    early = datetime(2026, 10, 27, 5, 0, tzinfo=timezone.utc)      # 06:00 Berlin
    late = datetime(2026, 10, 27, 7, 30, tzinfo=timezone.utc)      # 08:30 Berlin
    b.tick(early)
    assert not [m for m in tg.sent() if "Digest" in m["text"]]
    b.tick(late); b.tick(late)
    d = [m for m in tg.sent() if "Digest" in m["text"]]
    assert len(d) == 1 and "stumm" in d[0]["text"] and "Keine (aktuelle) Meldung" in d[0]["text"]
    b2 = B.Bot(tg, api, B.State(tmp_path / "s.db"), [111])         # Neustart, gleicher Zustand
    b2.tick(late)
    assert len([m for m in tg.sent() if "Digest" in m["text"]]) == 1


def test_server_outage_is_not_reported_as_backup_failure(bot):
    b, tg, api = bot
    api.down = True
    for _ in range(3):
        b.tick()
    down = [m for m in tg.sent() if "nicht erreichbar" in m["text"]]
    assert len(down) == 1 and "kein" in down[0]["text"]
    b.tick()
    assert len([m for m in tg.sent() if "nicht erreichbar" in m["text"]]) == 1   # nur einmal je Ausfall
    api.down = False
    b.tick()
    assert any("wieder erreichbar" in m["text"] for m in tg.sent())


def test_long_messages_are_chunked_and_escaped():
    parts = B.chunk("\n".join("x" * 100 for _ in range(100)))
    assert len(parts) > 1 and all(len(p) <= B.MAX_MSG for p in parts)
    assert B.esc("<a>&") == "&lt;a&gt;&amp;"
