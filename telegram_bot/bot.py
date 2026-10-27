"""hAI.BackupServer Telegram-Admin-Bot (Long-Polling, kein oeffentlicher Webhook noetig).

Sicherheit: Default-Deny. Nur Nutzer-IDs aus TELEGRAM_ALLOWED_USER_IDS im Privatchat duerfen
Befehle UND Buttons nutzen. Keine Passwoerter oder Scripte werden gesendet.
Ein Ausfall des Bots beeintraechtigt weder Backups noch die Report-Annahme.
"""
import html
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("hai-bot")
HOST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_MSG = 3800
ICON = {"ok": "✅", "warning": "⚠️", "error": "🔴", "running": "⏳", "overdue": "🕑", "no_report": "❔",
        "paused": "⏸️", "unknown": "❓"}
LABEL = {"ok": "OK", "warning": "Warnung", "error": "Fehler", "running": "läuft", "overdue": "überfällig",
         "no_report": "keine Meldung", "paused": "pausiert", "unknown": "unklar"}


class ApiError(Exception):
    pass


class TgError(Exception):
    pass


def esc(x):
    return html.escape(str(x), quote=False)


def chunk(text, size=MAX_MSG):
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > size:
            if cur:
                out.append(cur); cur = ""
            out.append(line[:size]); line = line[size:]
        if len(cur) + len(line) + 1 > size:
            out.append(cur); cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out or [""]


def human_size(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


class State:
    """Persistenter Zustand (Cursor, Digest-Datum, gesendete Meldungen)."""

    def __init__(self, path):
        self.c = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.c.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")

    def get(self, k, default=None):
        r = self.c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r[0] if r else default

    def set(self, k, v):
        self.c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))

    def delete(self, k):
        self.c.execute("DELETE FROM kv WHERE k=?", (k,))


class Api:
    def __init__(self, base, user, password, session=None):
        self.base, self.auth, self.s = base.rstrip("/"), (user, password), session or requests.Session()

    def _call(self, method, path, actor, **kw):
        try:
            r = self.s.request(method, self.base + path, auth=self.auth, timeout=15,
                               headers={"X-Requested-With": "hai-telegram-bot", "X-Actor": actor}, **kw)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            raise ApiError(str(e))

    def get(self, path, params=None, actor="telegram:bot"):
        return self._call("GET", path, actor, params=params)

    def post(self, path, json=None, actor="telegram:bot"):
        return self._call("POST", path, actor, json=json or {})


class Telegram:
    def __init__(self, token, session=None):
        self.url, self.s = f"https://api.telegram.org/bot{token}/", session or requests.Session()

    def call(self, method, timeout=15, **params):
        try:
            r = self.s.post(self.url + method, json=params, timeout=timeout + 10)
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            raise TgError(str(e))
        if not data.get("ok"):
            raise TgError(str(data.get("description", "unbekannter Telegram-Fehler")))
        return data["result"]


DOWN = "⚠️ <b>Backup-Server nicht erreichbar.</b> Das sagt nichts über den Zustand der Backups aus."


def kb(rows):
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


MENU = kb([[("📊 Status", "st"), ("🖥️ Hosts", "ho")], [("📰 Digest-Vorschau", "dg"), ("🩺 Health", "he")],
           [("ℹ️ Hilfe", "hl")]])
BACK = kb([[("⬅️ Menü", "m")]])


def fmt_status(st):
    c = st.get("counts", {})
    lines = ["<b>📊 Backup-Status</b>"]
    lines.append(" · ".join(f"{ICON[k]} {LABEL[k]}: {c[k]}" for k in ICON if c.get(k)) or "Keine Hosts konfiguriert.")
    for h in st.get("hosts", []):
        extra = f" – {esc(h['detail'])}" if h.get("detail") else ""
        lines.append(f"{ICON.get(h['state'], '❔')} <b>{esc(h['host_name'])}</b> ({esc(h['host_id'])}): {LABEL.get(h['state'], h['state'])}{extra}")
    return "\n".join(lines)


def fmt_digest(d):
    lines = [f"<b>📰 Backup-Digest</b> (letzte {d.get('hours', 24):g} h, {d.get('runs_in_window', 0)} Läufe)"]
    c = d.get("counts", {})
    lines.append(" · ".join(f"{ICON[k]} {LABEL[k]}: {c[k]}" for k in ICON if c.get(k)) or "Keine Hosts.")
    att = d.get("attention", [])
    if att:
        lines.append("\n<b>Handlungsbedarf</b>")
        for h in att:
            lines.append(f"{ICON.get(h['state'], '❔')} {esc(h['host_name'])}: {LABEL.get(h['state'], h['state'])}"
                         + (f" – {esc(h['detail'])}" if h.get("detail") else ""))
    ok = [h for h in d.get("hosts", []) if h["state"] == "ok"]
    if ok:
        lines.append("\n<b>Erfolgreich</b>")
        for h in ok:
            last = h.get("last") or {}
            lines.append(f"✅ {esc(h['host_name'])} – {human_size(last.get('size_bytes'))}, {int(last.get('duration_seconds') or 0)} s")
    silent = [h for h in d.get("hosts", []) if h["state"] in ("no_report", "overdue", "unknown")]
    if silent:
        lines.append("\n<b>Keine (aktuelle) Meldung von:</b> " + ", ".join(esc(h["host_name"]) for h in silent))
    return "\n".join(lines)


def fmt_event(ev):
    p = ev.get("payload", {})
    return (f"🔴 <b>Backup-Fehler</b>: {esc(p.get('host_name') or ev['host_id'])} (ID {esc(ev['host_id'])})\n"
            f"Exit-Code {esc(p.get('exit_code', '?'))} · {esc(ev.get('created_at', ''))}\n{esc(str(p.get('message', ''))[:600])}")


class Bot:
    def __init__(self, tg, api, state, allowed, tz="Europe/Berlin", digest_time="08:00", web_url=""):
        self.tg, self.api, self.state, self.allowed = tg, api, state, set(allowed)
        self.tz, self.web_url = ZoneInfo(tz), web_url
        hh, mm = digest_time.split(":")
        self.digest_minutes = int(hh) * 60 + int(mm)
        self.api_fail = 0

    # ---- Berechtigung (Nachrichten UND Buttons) ----
    def allowed_user(self, user_id, chat_type):
        return chat_type == "private" and user_id in self.allowed

    # ---- Senden ----
    def send(self, chat_id, text, markup=None):
        parts = chunk(text)
        for i, part in enumerate(parts):
            params = dict(chat_id=chat_id, text=part, parse_mode="HTML", disable_web_page_preview=True)
            if markup and i == len(parts) - 1:
                params["reply_markup"] = markup
            self.tg.call("sendMessage", **params)

    def show(self, cb, text, markup=None):
        msg = cb.get("message") or {}
        try:
            self.tg.call("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"], text=chunk(text)[0],
                         parse_mode="HTML", disable_web_page_preview=True, **({"reply_markup": markup} if markup else {}))
        except (TgError, KeyError):
            self.send(cb["from"]["id"], text, markup)

    def broadcast(self, text, key):
        """Sendet an alle erlaubten Nutzer; pro Nutzer nur einmal (Dedup ueber State)."""
        failed = None
        for uid in sorted(self.allowed):
            k = f"sent:{key}:{uid}"
            if self.state.get(k):
                continue
            try:
                self.send(uid, text)
                self.state.set(k, "1")
            except TgError as e:
                failed = e
        if failed:
            raise failed

    # ---- Eingehende Updates ----
    def handle_update(self, upd):
        if "callback_query" in upd:
            cb = upd["callback_query"]
            chat_type = ((cb.get("message") or {}).get("chat") or {}).get("type")
            if not self.allowed_user(cb["from"]["id"], chat_type):
                log.warning("Button von nicht erlaubtem Nutzer %s ignoriert", cb["from"]["id"])
                try:
                    self.tg.call("answerCallbackQuery", callback_query_id=cb["id"], text="Nicht berechtigt", show_alert=True)
                except TgError:
                    pass
                return
            self.on_callback(cb)
        elif "message" in upd:
            m = upd["message"]
            if not self.allowed_user((m.get("from") or {}).get("id"), (m.get("chat") or {}).get("type")):
                log.warning("Nachricht von nicht erlaubtem Nutzer ignoriert")
                return
            text = (m.get("text") or "").strip().split("@")[0]
            if text in ("/start", "/admin", "/menu"):
                self.send(m["chat"]["id"], "<b>🗄️ hAI.BackupServer – Admin</b>\nWähle eine Funktion:", MENU)
            elif text == "/status":
                self.send(m["chat"]["id"], self.safe(lambda: fmt_status(self.api.get("/api/status"))), BACK)
            else:
                self.send(m["chat"]["id"], "Nutze /admin für das Menü.", MENU)

    def safe(self, fn):
        try:
            return fn()
        except ApiError:
            return DOWN

    def on_callback(self, cb):
        uid, data = cb["from"]["id"], cb.get("data", "")
        actor = f"telegram:{uid}"
        try:
            self.tg.call("answerCallbackQuery", callback_query_id=cb["id"])
        except TgError:
            pass
        parts = data.split(":")
        act = parts[0]
        hid = parts[1] if len(parts) > 1 else ""
        if act in ("h", "hi", "rg", "rgy", "pa", "pay") and not HOST_ID_RE.match(hid):
            return
        if act == "m":
            self.show(cb, "<b>🗄️ hAI.BackupServer – Admin</b>\nWähle eine Funktion:", MENU)
        elif act == "st":
            self.show(cb, self.safe(lambda: fmt_status(self.api.get("/api/status"))), BACK)
        elif act == "ho":
            try:
                hs = self.api.get("/api/status")["hosts"]
                rows = [[(f"{ICON.get(h['state'], '❔')} {h['host_name']}", f"h:{h['host_id']}")] for h in hs]
                self.show(cb, "<b>🖥️ Hosts</b>", kb(rows + [[("⬅️ Menü", "m")]]))
            except ApiError:
                self.show(cb, DOWN, BACK)
        elif act == "h":
            def detail():
                h = next((x for x in self.api.get("/api/status")["hosts"] if x["host_id"] == hid), None)
                if not h:
                    return "Host nicht gefunden.", BACK
                last = h.get("last") or {}
                text = (f"{ICON.get(h['state'], '❔')} <b>{esc(h['host_name'])}</b> ({esc(hid)}): {LABEL.get(h['state'], h['state'])}\n"
                        + (f"{esc(h['detail'])}\n" if h.get("detail") else "")
                        + f"Letzter Lauf: {esc(last.get('first_seen_at', '–'))}\nLetzter Erfolg: {esc(h.get('last_success_at') or '–')}\n"
                        + (f"Meldung: {esc(str(last.get('message', ''))[:300])}" if last else ""))
                pa = "0" if h.get("paused") else "1"
                return text, kb([[("📜 Verlauf", f"hi:{hid}"), ("🔄 Script neu generieren", f"rg:{hid}")],
                                 [("▶️ Monitoring fortsetzen" if h.get("paused") else "⏸️ Monitoring pausieren", f"pa:{hid}:{pa}")],
                                 [("⬅️ Hosts", "ho")]])
            try:
                t, mk = detail()
                self.show(cb, t, mk)
            except ApiError:
                self.show(cb, DOWN, BACK)
        elif act == "hi":
            try:
                runs = self.api.get("/api/runs", params={"host_id": hid, "limit": 8})["runs"]
                body = "\n".join(f"{ICON.get(r['status'], '❔')} {esc(r['first_seen_at'])} · {int(r['duration_seconds'])} s · {human_size(r['size_bytes'])}" for r in runs)
                self.show(cb, f"<b>📜 Verlauf {esc(hid)}</b>\n{body or 'Noch keine Läufe.'}", kb([[("⬅️ Host", f"h:{hid}")]]))
            except ApiError:
                self.show(cb, DOWN, BACK)
        elif act == "rg":
            self.show(cb, f"Script für Host <b>{esc(hid)}</b> neu generieren?\nDer Client übernimmt es nur bei aktiviertem Auto-Update oder erneutem Download.",
                      kb([[("✅ Ja, generieren", f"rgy:{hid}"), ("❌ Abbrechen", f"h:{hid}")]]))
        elif act == "rgy":
            try:
                self.api.post(f"/api/hosts/{hid}/regenerate", actor=actor)
                self.show(cb, f"✅ Script für {esc(hid)} neu generiert.", kb([[("⬅️ Host", f"h:{hid}")]]))
            except ApiError:
                self.show(cb, "⚠️ Aktion fehlgeschlagen (Server nicht erreichbar oder Host unbekannt).", BACK)
        elif act == "pa" and len(parts) == 3 and parts[2] in ("0", "1"):
            what = "pausieren" if parts[2] == "1" else "fortsetzen"
            self.show(cb, f"Monitoring für Host <b>{esc(hid)}</b> {what}?",
                      kb([[("✅ Ja", f"pay:{hid}:{parts[2]}"), ("❌ Abbrechen", f"h:{hid}")]]))
        elif act == "pay" and len(parts) == 3 and parts[2] in ("0", "1"):
            try:
                self.api.post(f"/api/hosts/{hid}/pause", json={"paused": parts[2] == "1"}, actor=actor)
                self.show(cb, f"✅ Monitoring für {esc(hid)} {'pausiert' if parts[2] == '1' else 'fortgesetzt'}.", kb([[("⬅️ Host", f"h:{hid}")]]))
            except ApiError:
                self.show(cb, "⚠️ Aktion fehlgeschlagen.", BACK)
        elif act == "dg":
            self.show(cb, self.safe(lambda: fmt_digest(self.api.get("/api/digest"))), BACK)
        elif act == "he":
            def health():
                h = self.api.get("/api/health")
                return f"🩺 Server: <b>{esc(h.get('status'))}</b> (v{esc(h.get('version', '?'))})\n{esc(self.web_url)}"
            self.show(cb, self.safe(health), BACK)
        elif act == "hl":
            self.show(cb, "<b>ℹ️ Hilfe</b>\nFehler kommen sofort. Erfolge einmal täglich als Digest. Der Digest nennt auch Hosts ohne Meldung. "
                          "Änderungen (Pausieren, Script generieren) erfordern eine Bestätigung und werden im Audit-Log protokolliert.", BACK)

    # ---- Periodische Aufgaben (Ausfaelle hier duerfen nichts anderes beeintraechtigen) ----
    def tick(self, now=None):
        api_down = False
        for task in (self.poll_events, self.check_overdue, lambda: self.maybe_digest(now)):
            try:
                task()
            except ApiError as e:
                api_down = True
                log.warning("API nicht erreichbar: %s", e)
                break
            except TgError as e:
                log.warning("Telegram-Fehler, wird erneut versucht: %s", e)
        if api_down:
            self.api_fail += 1
            if self.api_fail >= 3 and not self.state.get("server_down"):
                try:
                    self.broadcast("⚠️ <b>Backup-Server nicht erreichbar</b>. Das ist <u>kein</u> gemeldeter Backup-Fehler.", f"down:{time.time_ns()}")
                    self.state.set("server_down", "1")
                except TgError:
                    pass
        else:
            self.api_fail = 0
            if self.state.get("server_down"):
                try:
                    self.broadcast("✅ Backup-Server wieder erreichbar.", f"up:{time.time_ns()}")
                    self.state.delete("server_down")
                except TgError:
                    pass

    def poll_events(self):
        cursor = int(self.state.get("event_cursor", "0"))
        for ev in self.api.get("/api/events", params={"after": cursor, "types": "run_error"})["events"]:
            self.broadcast(fmt_event(ev), f"event:{ev['id']}")
            self.state.set("event_cursor", ev["id"])

    def check_overdue(self):
        for h in self.api.get("/api/status")["hosts"]:
            if h["state"] in ("overdue", "unknown") and not h.get("paused"):
                last = (h.get("last") or {}).get("run_id", "none")
                self.broadcast(f"🕑 <b>Überfällig</b>: {esc(h['host_name'])} ({esc(h['host_id'])}) – {esc(h.get('detail', ''))}",
                               f"overdue:{h['host_id']}:{last}")

    def maybe_digest(self, now=None):
        local = (now or datetime.now(timezone.utc)).astimezone(self.tz)
        today = local.date().isoformat()
        if local.hour * 60 + local.minute >= self.digest_minutes and self.state.get("last_digest") != today:
            self.broadcast(fmt_digest(self.api.get("/api/digest")), f"digest:{today}")
            self.state.set("last_digest", today)

    def run_forever(self):
        offset, fails, last_tick = int(self.state.get("tg_offset", "0")), 0, 0.0
        while True:
            try:
                for upd in self.tg.call("getUpdates", timeout=25, offset=offset, allowed_updates=["message", "callback_query"]):
                    offset = upd["update_id"] + 1
                    self.state.set("tg_offset", offset)
                    try:
                        self.handle_update(upd)
                    except Exception:      # ein defektes Update darf den Bot nicht stoppen
                        log.exception("Fehler bei Update")
                fails = 0
            except TgError as e:
                fails += 1
                log.warning("getUpdates fehlgeschlagen: %s", e)
                time.sleep(min(60, 2 ** fails))
            if time.time() - last_tick >= 30:
                self.tick()
                last_tick = time.time()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    allowed = [int(x) for x in re.findall(r"\d+", os.environ.get("TELEGRAM_ALLOWED_USER_IDS", ""))]
    if not token or not allowed:
        log.warning("TELEGRAM_BOT_TOKEN und/oder TELEGRAM_ALLOWED_USER_IDS fehlen - Bot bleibt inaktiv (Default-Deny).")
        while True:
            time.sleep(3600)
    api = Api(os.environ.get("BACKUP_API_BASE_URL", "http://backup-orchestrator:8080"),
              os.environ.get("BACKUP_API_USER", "admin"), os.environ.get("BACKUP_API_PASSWORD", ""))
    state = State(os.environ.get("BOT_DB_PATH", "/data/bot.db"))
    bot = Bot(Telegram(token), api, state, allowed, os.environ.get("DIGEST_TZ", "Europe/Berlin"),
              os.environ.get("DIGEST_TIME", "08:00"), os.environ.get("WEB_BASE_URL", ""))
    log.info("Bot gestartet fuer %d erlaubte(n) Nutzer", len(allowed))
    bot.run_forever()


if __name__ == "__main__":
    main()
