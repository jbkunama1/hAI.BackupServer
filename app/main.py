"""hAI.BackupServer - zentrales Backup-Control-Center.

Web-UI + REST-API (mit HTTP Basic Auth) zur Verwaltung von Backup-Hosts und
automatischen Generierung der pro Host individuellen full_backup_<HOST_ID>.sh
Scripte auf Basis von hAI.FullBackupScript.
"""
import os
import secrets
import shutil
from pathlib import Path
from typing import List, Optional

import yaml
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from models import ContainerConfig, DbContainerConfig, HostConfig
from script_generator import render_backup_script, render_bootstrap_script

BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "hosts.yml"
CONFIG_EXAMPLE = CONFIG_DIR / "hosts.yml.example"
GENERATED_DIR = Path(os.environ.get("GENERATED_DIR", "/app/generated"))
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

ORCHESTRATOR_HOST = os.environ.get("ORCHESTRATOR_HOST", "192.168.178.26")
CRON_SCHEDULE = os.environ.get("CRON_SCHEDULE", "0 3 * * *")

# --------------------------------------------------------------------------
# HTTP Basic Auth (schuetzt Web-UI, Script-/Bootstrap-Endpunkte und JSON-API)
# --------------------------------------------------------------------------
BASIC_AUTH_USER = os.environ.get("BASIC_AUTH_USER", "admin")
BASIC_AUTH_PASSWORD = os.environ.get("BASIC_AUTH_PASSWORD", "")

_security = HTTPBasic()


def require_basic_auth(credentials: HTTPBasicCredentials = Depends(_security)) -> str:
    if not BASIC_AUTH_PASSWORD:
        # Fail-closed: ohne gesetztes Passwort ist der Server nicht nutzbar.
        raise HTTPException(
            status_code=500,
            detail="BASIC_AUTH_PASSWORD ist nicht gesetzt. Bitte als Umgebungsvariable konfigurieren.",
        )
    correct_user = secrets.compare_digest(credentials.username, BASIC_AUTH_USER)
    correct_pass = secrets.compare_digest(credentials.password, BASIC_AUTH_PASSWORD)
    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=401,
            detail="Ungueltige Zugangsdaten",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


app = FastAPI(
    title="hAI.BackupServer",
    version="1.1.0",
    dependencies=[Depends(require_basic_auth)],
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _ensure_config() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists() and CONFIG_EXAMPLE.exists():
        shutil.copy(CONFIG_EXAMPLE, CONFIG_FILE)


def load_config() -> dict:
    _ensure_config()
    if not CONFIG_FILE.exists():
        return {
            "nas_mount_default": "highfishNAS25",
            "nas_base_path": "/mnt/highfishNAS25/Sicherung",
            "notifications": {"enabled": False, "method": "ntfy",
                               "ntfy_topic": "hai-backup-alerts",
                               "ntfy_server": "https://ntfy.sh", "email_to": ""},
            "versioning": {"enabled": False, "keep_count": 5},
            "hosts": [],
        }
    with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)


def get_hosts(cfg: dict) -> List[HostConfig]:
    return [HostConfig.from_dict(h) for h in cfg.get("hosts", [])]


def find_host(cfg: dict, host_id: str) -> Optional[HostConfig]:
    for h in get_hosts(cfg):
        if h.host_id == str(host_id):
            return h
    return None


def upsert_host(cfg: dict, host: HostConfig) -> None:
    hosts = cfg.setdefault("hosts", [])
    for i, h in enumerate(hosts):
        if str(h.get("host_id")) == host.host_id:
            hosts[i] = host.to_dict()
            return
    hosts.append(host.to_dict())


def _parse_containers(raw: str) -> List[ContainerConfig]:
    result = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(";")]
        name = parts[0]
        vol = parts[1] if len(parts) > 1 and parts[1] else None
        result.append(ContainerConfig(name=name, volume_source_path=vol))
    return result


def _parse_db_containers(raw: str) -> List[DbContainerConfig]:
    result = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(";")]
        name = parts[0]
        user = parts[1] if len(parts) > 1 and parts[1] else "postgres"
        result.append(DbContainerConfig(name=name, db_user=user))
    return result


def _write_generated_script(host: HostConfig, cfg: dict) -> Path:
    notif = cfg.get("notifications", {})
    vers = cfg.get("versioning", {})
    script = render_backup_script(
        host=host,
        nas_base_path=cfg.get("nas_base_path", "/mnt/highfishNAS25/Sicherung"),
        notifications_enabled=notif.get("enabled", False),
        notification_method=notif.get("method", "ntfy"),
        ntfy_topic=notif.get("ntfy_topic", "hai-backup-alerts"),
        ntfy_server=notif.get("ntfy_server", "https://ntfy.sh"),
        email_to=notif.get("email_to", ""),
        versioning_enabled=vers.get("enabled", False),
        versioning_keep_count=vers.get("keep_count", 5),
        orchestrator_host=ORCHESTRATOR_HOST,
    )
    out_path = GENERATED_DIR / f"full_backup_{host.host_id}.sh"
    out_path.write_text(script, encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------
# Web-UI
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    cfg = load_config()
    hosts = get_hosts(cfg)
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "hosts": hosts,
        "nas_mount_default": cfg.get("nas_mount_default", "highfishNAS25"),
        "nas_base_path": cfg.get("nas_base_path", "/mnt/highfishNAS25/Sicherung"),
        "orchestrator_host": ORCHESTRATOR_HOST,
    })


@app.get("/hosts/new", response_class=HTMLResponse)
def new_host_form(request: Request):
    cfg = load_config()
    return templates.TemplateResponse("host_form.html", {
        "request": request,
        "host": None,
        "action_url": "/hosts/new",
        "nas_mount_default": cfg.get("nas_mount_default", "highfishNAS25"),
        "containers_raw": "",
        "db_containers_raw": "",
    })


@app.post("/hosts/new")
def create_host(
    host_name: str = Form(...),
    host_id: str = Form(...),
    nas_mount: str = Form(...),
    containers_raw: str = Form(""),
    db_containers_raw: str = Form(""),
):
    cfg = load_config()
    if find_host(cfg, host_id):
        raise HTTPException(400, f"Host-ID {host_id} existiert bereits.")
    host = HostConfig(
        host_name=host_name,
        host_id=host_id,
        nas_mount=nas_mount,
        containers=_parse_containers(containers_raw),
        db_containers=_parse_db_containers(db_containers_raw),
    )
    upsert_host(cfg, host)
    save_config(cfg)
    _write_generated_script(host, cfg)
    return RedirectResponse(f"/hosts/{host_id}", status_code=303)


@app.get("/hosts/{host_id}", response_class=HTMLResponse)
def host_detail(request: Request, host_id: str):
    cfg = load_config()
    host = find_host(cfg, host_id)
    if not host:
        raise HTTPException(404, "Host nicht gefunden")
    return templates.TemplateResponse("host_detail.html", {
        "request": request,
        "host": host,
        "orchestrator_host": ORCHESTRATOR_HOST,
        "basic_auth_user": BASIC_AUTH_USER,
    })


@app.get("/hosts/{host_id}/edit", response_class=HTMLResponse)
def edit_host_form(request: Request, host_id: str):
    cfg = load_config()
    host = find_host(cfg, host_id)
    if not host:
        raise HTTPException(404, "Host nicht gefunden")
    containers_raw = "\n".join(
        f"{c.name};{c.volume_source_path or ''}" for c in host.containers
    )
    db_containers_raw = "\n".join(
        f"{d.name};{d.db_user}" for d in host.db_containers
    )
    return templates.TemplateResponse("host_form.html", {
        "request": request,
        "host": host,
        "action_url": f"/hosts/{host_id}/edit",
        "nas_mount_default": cfg.get("nas_mount_default", "highfishNAS25"),
        "containers_raw": containers_raw,
        "db_containers_raw": db_containers_raw,
    })


@app.post("/hosts/{host_id}/edit")
def update_host(
    host_id: str,
    host_name: str = Form(...),
    nas_mount: str = Form(...),
    containers_raw: str = Form(""),
    db_containers_raw: str = Form(""),
):
    cfg = load_config()
    if not find_host(cfg, host_id):
        raise HTTPException(404, "Host nicht gefunden")
    host = HostConfig(
        host_name=host_name,
        host_id=host_id,
        nas_mount=nas_mount,
        containers=_parse_containers(containers_raw),
        db_containers=_parse_db_containers(db_containers_raw),
    )
    upsert_host(cfg, host)
    save_config(cfg)
    _write_generated_script(host, cfg)
    return RedirectResponse(f"/hosts/{host_id}", status_code=303)


# --------------------------------------------------------------------------
# Script-/Bootstrap-Auslieferung (fuer Hosts + Agenten/MCP)
# --------------------------------------------------------------------------
@app.get("/script/{host_id}", response_class=PlainTextResponse, summary="Aktuelles Backup-Script eines Hosts abrufen")
def get_script(host_id: str):
    """Rendert und liefert das aktuelle full_backup_<HOST_ID>.sh fuer den angegebenen Host."""
    cfg = load_config()
    host = find_host(cfg, host_id)
    if not host:
        raise HTTPException(404, f"Host-ID {host_id} nicht konfiguriert")
    script_path = _write_generated_script(host, cfg)
    return PlainTextResponse(script_path.read_text(encoding="utf-8"), media_type="text/x-shellscript")


@app.get("/bootstrap/{host_id}", response_class=PlainTextResponse, summary="Bootstrap-Script fuer einen neuen Host abrufen")
def get_bootstrap(host_id: str):
    """Liefert das einmalig auf einem neuen Server auszufuehrende Bootstrap-Script."""
    cfg = load_config()
    host = find_host(cfg, host_id)
    if not host:
        raise HTTPException(404, f"Host-ID {host_id} nicht konfiguriert")
    script = render_bootstrap_script(
        host, ORCHESTRATOR_HOST, CRON_SCHEDULE,
        basic_auth_user=BASIC_AUTH_USER,
        basic_auth_password=BASIC_AUTH_PASSWORD,
    )
    return PlainTextResponse(script, media_type="text/x-shellscript")


# --------------------------------------------------------------------------
# JSON-API (fuer MCP-Tools / Agenten) - jeder Endpoint einzeln dokumentiert,
# damit ein MCP-/OpenAPI-Import saubere Tool-Namen und Beschreibungen erzeugt.
# --------------------------------------------------------------------------
@app.get("/api/hosts", summary="Alle Backup-Hosts auflisten", tags=["backup-hosts"])
def api_list_hosts():
    """Gibt alle in hosts.yml konfigurierten Backup-Hosts zurueck."""
    cfg = load_config()
    return {"hosts": [h.to_dict() for h in get_hosts(cfg)]}


@app.get("/api/hosts/{host_id}", summary="Details zu einem Backup-Host", tags=["backup-hosts"])
def api_get_host(host_id: str):
    """Gibt Hostname, NAS-Mount, Container und DB-Container eines Hosts zurueck."""
    cfg = load_config()
    host = find_host(cfg, host_id)
    if not host:
        raise HTTPException(404, f"Host-ID {host_id} nicht konfiguriert")
    return host.to_dict()


@app.post("/api/hosts", summary="Backup-Host anlegen oder aktualisieren", tags=["backup-hosts"])
def api_create_or_update_host(payload: dict):
    """Legt einen Host an oder aktualisiert ihn (per host_id) und generiert sofort das Backup-Script."""
    cfg = load_config()
    host = HostConfig.from_dict(payload)
    upsert_host(cfg, host)
    save_config(cfg)
    _write_generated_script(host, cfg)
    return {"status": "ok", "host": host.to_dict()}


@app.post("/api/hosts/{host_id}/regenerate", summary="Backup-Script neu generieren", tags=["backup-hosts"])
def api_regenerate_script(host_id: str):
    """Erzwingt die Neugenerierung des Backup-Scripts fuer einen Host (z.B. nach Config-Aenderung)."""
    cfg = load_config()
    host = find_host(cfg, host_id)
    if not host:
        raise HTTPException(404, f"Host-ID {host_id} nicht konfiguriert")
    path = _write_generated_script(host, cfg)
    return {"status": "ok", "script_path": str(path)}


@app.get("/api/health", summary="Health-Check", tags=["system"])
def health():
    return {"status": "ok", "service": "hAI.BackupServer"}
