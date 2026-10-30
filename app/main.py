"""hAI.BackupServer - HTTP-Schicht (duenn; die Logik liegt in service.py).

Zugriffsmodell:
  * Admin (HTTP Basic Auth): Web-UI und Verwaltungs-API
  * Host-Token (Header X-Host-Token): nur Script-Abruf und Report des eigenen Hosts
  * Enroll-Token (Header X-Enroll-Token): nur POST /api/enroll
"""
import hashlib
import hmac
import os
import re
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import confstore as cs
import ui
import validation as v
from models import HostConfig
from service import NotFound, Service
from store import Store, now_iso

VERSION = "2.0.0"
BASE_DIR = Path(__file__).parent
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", BASE_DIR / "config"))
GENERATED_DIR = Path(os.environ.get("GENERATED_DIR", "/app/generated"))
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

ORCHESTRATOR_HOST = os.environ.get("ORCHESTRATOR_HOST", "192.168.178.26")
BASIC_AUTH_USER = os.environ.get("BASIC_AUTH_USER", "admin")
BASIC_AUTH_PASSWORD = os.environ.get("BASIC_AUTH_PASSWORD", "")
ENROLL_TOKEN = os.environ.get("ENROLL_TOKEN", "")

svc = Service(
    cs.ConfigStore(CONFIG_DIR / "hosts.yml", CONFIG_DIR / "hosts.yml.example"),
    Store(os.environ.get("DB_PATH", str(CONFIG_DIR / "backupserver.db"))),
    ORCHESTRATOR_HOST, os.environ.get("CRON_SCHEDULE", "0 3 * * *"), ENROLL_TOKEN, GENERATED_DIR)

app = FastAPI(title="hAI.BackupServer", version=VERSION)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
ui.register(templates.env)

_basic = HTTPBasic(auto_error=False)
_ACTOR_RE = re.compile(r"^[A-Za-z0-9:_.@ -]{1,100}$")


# ---------------------------------------------------------------- Auth ----
def _basic_ok(creds: Optional[HTTPBasicCredentials]) -> bool:
    if not BASIC_AUTH_PASSWORD:      # fail-closed
        raise HTTPException(500, "BASIC_AUTH_PASSWORD ist nicht gesetzt. Bitte als Umgebungsvariable konfigurieren.")
    if not creds:
        return False
    return (secrets.compare_digest(creds.username.encode(), BASIC_AUTH_USER.encode())
            & secrets.compare_digest(creds.password.encode(), BASIC_AUTH_PASSWORD.encode()))


def _unauthorized():
    return HTTPException(401, "Ungueltige Zugangsdaten", headers={"WWW-Authenticate": "Basic"})


def require_admin(request: Request, creds: Optional[HTTPBasicCredentials] = Depends(_basic)) -> str:
    if not _basic_ok(creds):
        raise _unauthorized()
    actor = request.headers.get("x-actor", "")
    return actor if _ACTOR_RE.match(actor) else creds.username


def host_or_admin(host_id: str, creds: Optional[HTTPBasicCredentials] = Depends(_basic),
                  x_host_token: Optional[str] = Header(None)) -> str:
    if x_host_token is not None:
        if not svc.verify_host_token(host_id, x_host_token):
            raise HTTPException(403, "Ungueltiges Host-Token")
        return f"host:{host_id}"
    if _basic_ok(creds):
        return creds.username
    raise _unauthorized()


def require_xhr(x_requested_with: Optional[str] = Header(None)) -> None:
    """Schutz vor Cross-Site-Formularposts auf mutierende JSON-Endpunkte."""
    if not x_requested_with:
        raise HTTPException(400, "Header X-Requested-With fehlt")


def csrf_token(user: str) -> str:
    return hmac.new(BASIC_AUTH_PASSWORD.encode(), f"csrf-v1:{user}".encode(), hashlib.sha256).hexdigest()


def check_csrf(user: str, token: str) -> None:
    if not token or not hmac.compare_digest(token, csrf_token(user)):
        raise HTTPException(403, "CSRF-Pruefung fehlgeschlagen - Seite neu laden")


@app.exception_handler(NotFound)
async def _nf(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(v.ValidationError)
async def _bad(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def page(request: Request, name: str, user: str, active: str, **ctx):
    ctx.update(active=active, csrf=csrf_token(user), orchestrator_host=ORCHESTRATOR_HOST,
               basic_auth_user=BASIC_AUTH_USER, enroll_enabled=bool(ENROLL_TOKEN))
    return templates.TemplateResponse(request, name, ctx)


# ------------------------------------------- Agenten: Enroll, Script, Report
@app.get("/enroll.sh", response_class=PlainTextResponse, summary="Universelles Enroll-Script (ohne Zugangsdaten)")
def enroll_script():
    return PlainTextResponse(svc.render_enroll(), media_type="text/x-shellscript")


@app.post("/api/enroll", summary="Host per Enroll-Token registrieren", tags=["enrollment"])
def api_enroll(payload: dict, format: str = "json", x_enroll_token: Optional[str] = Header(None)):
    if not ENROLL_TOKEN:
        raise HTTPException(503, "Enrollment ist nicht aktiviert (ENROLL_TOKEN nicht gesetzt)")
    if not x_enroll_token or not secrets.compare_digest(x_enroll_token.encode(), ENROLL_TOKEN.encode()):
        time.sleep(1)                      # bremst Durchprobieren
        raise HTTPException(403, "Ungueltiges Enroll-Token")
    res = svc.enroll(payload, bool(payload.get("update_config")))
    if format == "env":
        return PlainTextResponse(f"HOST_ID={res['host_id']}\nHOST_TOKEN={res['host_token']}\n"
                                 f"CRON_SCHEDULE={res['cron_schedule']}\n")
    return res


@app.get("/script/{host_id}", response_class=PlainTextResponse, summary="Aktuelles Backup-Script eines Hosts")
def get_script(host_id: str, _: str = Depends(host_or_admin)):
    svc.regenerate(host_id)
    return PlainTextResponse(svc.render_script(host_id), media_type="text/x-shellscript")


@app.post("/api/hosts/{host_id}/report", summary="Backup-Ergebnis melden", tags=["monitoring"])
def api_report(host_id: str, payload: dict, _: str = Depends(host_or_admin)):
    return {"status": "ok", "run": svc.submit_report(host_id, payload)["run"]}


# ------------------------------------------------------------- Admin-API --
@app.get("/bootstrap/{host_id}", response_class=PlainTextResponse, summary="Bootstrap-Script eines Hosts")
def get_bootstrap(host_id: str, _: str = Depends(require_admin)):
    return PlainTextResponse(svc.render_bootstrap(host_id), media_type="text/x-shellscript")


@app.get("/api/hosts", summary="Alle Backup-Hosts auflisten", tags=["backup-hosts"])
def api_list_hosts(_: str = Depends(require_admin)):
    return {"hosts": [h.public_dict() for h in cs.get_hosts(svc.cfg())]}


@app.get("/api/hosts/{host_id}", summary="Details zu einem Backup-Host", tags=["backup-hosts"])
def api_get_host(host_id: str, _: str = Depends(require_admin)):
    return svc.host(host_id).public_dict()


@app.post("/api/hosts", summary="Backup-Host anlegen oder aktualisieren", tags=["backup-hosts"])
def api_upsert_host(payload: dict, actor: str = Depends(require_admin)):
    host = HostConfig.from_dict(payload)
    existing = cs.find_host(svc.cfg(), host.host_id)
    if existing:                                   # nicht mitgeschickte Felder behalten (z. B. MCP-Upsert)
        for key in ("expected_interval_hours", "auto_update", "backup_dir_name"):
            if key not in payload:
                setattr(host, key, getattr(existing, key))
    return {"status": "ok", "host": svc.save_host(host, actor).public_dict()}


@app.post("/api/hosts/{host_id}/regenerate", summary="Backup-Script neu generieren", tags=["backup-hosts"])
def api_regenerate(host_id: str, actor: str = Depends(require_admin)):
    path = svc.regenerate(host_id)
    svc.store.audit(actor, "script_regenerate", host_id)
    return {"status": "ok", "script_path": path}


@app.post("/api/hosts/{host_id}/pause", summary="Monitoring pausieren/fortsetzen", tags=["monitoring"],
          dependencies=[Depends(require_xhr)])
def api_pause(host_id: str, payload: dict, actor: str = Depends(require_admin)):
    svc.set_paused(host_id, bool(payload.get("paused", True)), actor)
    return {"status": "ok", "paused": bool(payload.get("paused", True))}


@app.get("/api/hosts/{host_id}/report", summary="Letzten Report eines Hosts", tags=["monitoring"])
def api_last_report(host_id: str, _: str = Depends(require_admin)):
    svc.host(host_id)
    last = svc.store.last_run(host_id)
    if not last:
        raise HTTPException(404, f"Fuer Host-ID {host_id} liegt noch kein Report vor")
    return last


@app.get("/api/reports", summary="Letzter Lauf je Host (kompatibel)", tags=["monitoring"])
def api_reports(_: str = Depends(require_admin)):
    return {"reports": svc.store.latest_per_host()}


@app.get("/api/runs", summary="Laufhistorie", tags=["monitoring"])
def api_runs(host_id: Optional[str] = None, limit: int = 50, _: str = Depends(require_admin)):
    return {"runs": svc.store.list_runs(host_id, limit)}


@app.get("/api/status", summary="Abgeleiteter Status aller Hosts", tags=["monitoring"])
def api_status(_: str = Depends(require_admin)):
    return svc.status()


@app.get("/api/digest", summary="Zusammenfassung fuer Tagesdigest", tags=["monitoring"])
def api_digest(hours: float = 24, _: str = Depends(require_admin)):
    return svc.digest(hours)


@app.get("/api/events", summary="Ereignisse (Fehler) fuer den Telegram-Bot", tags=["monitoring"])
def api_events(after: int = 0, types: str = "run_error", limit: int = 100, actor: str = Depends(require_admin)):
    if actor.startswith("telegram"):
        svc.store.meta_set("bot_last_seen", now_iso())
    wanted = tuple(t for t in types.split(",") if re.fullmatch(r"[a-z_]{1,30}", t)) or ("run_error",)
    return {"events": svc.store.events_after(after, wanted, min(limit, 200))}


@app.get("/api/health", summary="Health-Check", tags=["system"])
def health(_: str = Depends(require_admin)):
    svc.store.meta_get("x")
    return {"status": "ok", "service": "hAI.BackupServer", "version": VERSION}


# ---------------------------------------------------------------- Web-UI --
@app.get("/")
def dashboard(request: Request, user: str = Depends(require_admin)):
    rows = svc.overview()
    counts = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    cfg = svc.cfg()
    return page(request, "dashboard.html", user, "dashboard", rows=rows, counts=counts,
                nas_base_path=cfg.get("nas_base_path", ""))


@app.get("/monitoring")
def monitoring_page(request: Request, host: str = "", user: str = Depends(require_admin)):
    return page(request, "monitoring.html", user, "monitoring", runs=svc.store.list_runs(host or None, 100),
                hosts=cs.get_hosts(svc.cfg()), selected=host)


@app.get("/enroll")
def enroll_page(request: Request, user: str = Depends(require_admin)):
    return page(request, "enroll.html", user, "enroll", nas_base_path=svc.cfg().get("nas_base_path", ""))


@app.get("/settings")
def settings_page(request: Request, user: str = Depends(require_admin)):
    return page(request, "settings.html", user, "settings", mon=cs.monitoring(svc.cfg()),
                bot_seen=svc.store.meta_get("bot_last_seen"), audit=svc.store.list_audit(15), version=VERSION)


@app.post("/settings")
async def settings_save(request: Request, user: str = Depends(require_admin)):
    form = dict(await request.form())
    check_csrf(user, str(form.get("csrf", "")))
    svc.update_settings(form, user)
    return RedirectResponse("/settings", status_code=303)


def _host_from_form(form: dict, host_id: str, default_dir: str = v.DEFAULT_BACKUP_DIR) -> HostConfig:
    return HostConfig(
        host_name=str(form.get("host_name", "")).strip(), host_id=host_id,
        nas_mount=str(form.get("nas_mount", "")).strip(),
        backup_dir_name=str(form.get("backup_dir_name") or "").strip() or default_dir,
        samba_share_path=str(form.get("samba_share_path") or "").strip() or None,
        samba_username=str(form.get("samba_username") or "").strip() or None,
        samba_password=str(form.get("samba_password") or "").strip() or None,
        containers=svc.parse_containers(str(form.get("containers_raw", ""))),
        db_containers=svc.parse_db_containers(str(form.get("db_containers_raw", ""))),
        expected_interval_hours=v.number(form.get("expected_interval_hours"), "Intervall", 1, 744, None),
        auto_update=bool(form.get("auto_update")))


@app.get("/hosts/new")
def new_host_form(request: Request, user: str = Depends(require_admin)):
    return page(request, "host_form.html", user, "new", host=None, action_url="/hosts/new", containers_raw="",
                db_containers_raw="", nas_mount_default=svc.cfg().get("nas_mount_default", "highfishNAS25"))


@app.post("/hosts/new")
async def create_host(request: Request, user: str = Depends(require_admin)):
    form = dict(await request.form())
    check_csrf(user, str(form.get("csrf", "")))
    host = svc.save_host(_host_from_form(form, str(form.get("host_id", "")).strip()), user, create_only=True)
    return RedirectResponse(f"/hosts/{host.host_id}", status_code=303)


@app.get("/hosts/{host_id}")
def host_detail(request: Request, host_id: str, user: str = Depends(require_admin)):
    host = svc.host(host_id)
    info = next(r for r in svc.overview() if r["host"]["host_id"] == host_id)
    return page(request, "host_detail.html", user, "dashboard", host=host, info=info,
                runs=svc.store.list_runs(host_id, 20))


@app.get("/hosts/{host_id}/edit")
def edit_host_form(request: Request, host_id: str, user: str = Depends(require_admin)):
    host = svc.host(host_id)
    raw_c = "\n".join(";".join([c.name, *c.all_paths()]) for c in host.containers)
    raw_d = "\n".join(f"{d.name};{d.db_user}" for d in host.db_containers)
    return page(request, "host_form.html", user, "dashboard", host=host, action_url=f"/hosts/{host_id}/edit",
                containers_raw=raw_c, db_containers_raw=raw_d, nas_mount_default="")


@app.post("/hosts/{host_id}/edit")
async def update_host(request: Request, host_id: str, user: str = Depends(require_admin)):
    form = dict(await request.form())
    check_csrf(user, str(form.get("csrf", "")))
    existing = svc.host(host_id)      # fehlt das Feld im Formular, bleibt der bisherige Verzeichnisname
    svc.save_host(_host_from_form(form, host_id, existing.backup_dir_name), user)
    return RedirectResponse(f"/hosts/{host_id}", status_code=303)


@app.post("/hosts/{host_id}/pause")
async def pause_form(request: Request, host_id: str, user: str = Depends(require_admin)):
    form = dict(await request.form())
    check_csrf(user, str(form.get("csrf", "")))
    svc.set_paused(host_id, str(form.get("paused", "1")) == "1", user)
    return RedirectResponse(f"/hosts/{host_id}", status_code=303)


@app.post("/hosts/{host_id}/delete")
async def delete_form(request: Request, host_id: str, user: str = Depends(require_admin)):
    form = dict(await request.form())
    check_csrf(user, str(form.get("csrf", "")))
    if str(form.get("confirm", "")).strip() != host_id:
        raise HTTPException(400, "Bestaetigung stimmt nicht mit der Host-ID ueberein")
    svc.delete_host(host_id, user)
    return RedirectResponse("/", status_code=303)
