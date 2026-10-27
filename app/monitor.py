"""Abgeleiteter Monitoring-Zustand (rein funktional, gut testbar)."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from store import parse_iso

STATE_LABELS = {
    "ok": "OK", "warning": "WARNUNG", "error": "FEHLER", "running": "LÄUFT",
    "overdue": "ÜBERFÄLLIG", "no_report": "KEINE MELDUNG", "paused": "PAUSIERT",
    "unknown": "UNKLAR",
}


def compute_state(host, last: Optional[dict], mon: dict, now: Optional[datetime] = None) -> dict:
    """Liefert state, overdue, detail. host: HostConfig, last: letzter Lauf oder None."""
    now = now or datetime.now(timezone.utc)
    interval = float(host.expected_interval_hours or mon["expected_interval_hours"])
    deadline = timedelta(hours=interval + float(mon["grace_hours"]))
    out = {"state": "no_report", "overdue": False, "detail": "", "interval_hours": interval}
    if host.monitoring_paused:
        out.update(state="paused", detail="Monitoring pausiert")
        return out
    if last is None:
        created = parse_iso(host.created_at)
        grace = timedelta(hours=float(mon["enroll_grace_hours"]))
        if created and now > created + grace:
            out.update(state="overdue", overdue=True,
                       detail="Seit der Einrichtung ist keine Meldung eingegangen")
        else:
            out.update(detail="Noch keine Meldung eingegangen (Einrichtungsfrist läuft)")
        return out
    seen = parse_iso(last.get("first_seen_at")) or now
    age = now - seen
    status = last["status"]
    if status == "running":
        if age > timedelta(hours=float(mon["max_run_hours"])):
            out.update(state="unknown", overdue=True,
                       detail="Lauf gestartet, aber nie abgeschlossen (Abbruch/Neustart?)")
        else:
            out.update(state="running", detail="Lauf aktiv")
        return out
    out["state"] = status
    out["overdue"] = age > deadline
    if out["overdue"]:
        out["detail"] = f"Letzte Meldung älter als {interval:g} h + Karenz"
        if status in ("ok", "warning"):
            out["state"] = "overdue"
    return out


def pill_class(state: str) -> str:
    return {"ok": "ok", "running": "info", "warning": "warn", "error": "err", "overdue": "err",
            "unknown": "warn", "no_report": "muted", "paused": "muted"}.get(state, "muted")
