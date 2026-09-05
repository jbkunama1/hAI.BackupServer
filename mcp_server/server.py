"""hAI.BackupServer MCP-Server.

Kapselt die JSON-API von hAI.BackupServer (main.py) als MCP-Tools, damit
Agenten (z.B. ueber das hAI.MCP-/AnythingMCP-Gateway) Backup-Hosts abfragen,
anlegen und Scripte generieren/abrufen koennen.

Laeuft als eigener Container/Prozess und spricht ueber HTTP (Basic Auth) mit
hAI.BackupServer. Transport: SSE (Server-Sent Events), damit ein Gateway wie
AnythingMCP den Server per URL einbinden kann.
"""
import os

import requests
from mcp.server.fastmcp import FastMCP

API_BASE_URL = os.environ.get("BACKUP_API_BASE_URL", "http://backup-orchestrator:8080")
API_USER = os.environ.get("BACKUP_API_USER", "admin")
API_PASSWORD = os.environ.get("BACKUP_API_PASSWORD", "")
REQUEST_TIMEOUT = float(os.environ.get("BACKUP_API_TIMEOUT", "15"))

mcp = FastMCP("hAI.BackupServer")


def _auth() -> tuple[str, str]:
    return (API_USER, API_PASSWORD)


def _get(path: str) -> requests.Response:
    resp = requests.get(f"{API_BASE_URL}{path}", auth=_auth(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp


def _post(path: str, json: dict | None = None) -> requests.Response:
    resp = requests.post(f"{API_BASE_URL}{path}", json=json, auth=_auth(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp


@mcp.tool()
def list_backup_hosts() -> dict:
    """Listet alle im hAI.BackupServer konfigurierten Backup-Hosts auf
    (Hostname, Host-ID, NAS-Mount, Anzahl Container/DB-Container)."""
    return _get("/api/hosts").json()


@mcp.tool()
def get_backup_host(host_id: str) -> dict:
    """Liefert die Detailkonfiguration eines einzelnen Backup-Hosts
    (Container inkl. Volume-Pfade, DB-Container inkl. DB-User)."""
    return _get(f"/api/hosts/{host_id}").json()


@mcp.tool()
def upsert_backup_host(
    host_name: str,
    host_id: str,
    nas_mount: str,
    containers: list[dict],
    db_containers: list[dict] | None = None,
) -> dict:
    """Legt einen neuen Backup-Host an oder aktualisiert einen bestehenden
    (per host_id) und generiert sofort das passende full_backup_<HOST_ID>.sh.

    containers: Liste von {"name": str, "volume_source_path": str|None}
    db_containers: Liste von {"name": str, "db_user": str}
    """
    payload = {
        "host_name": host_name,
        "host_id": host_id,
        "nas_mount": nas_mount,
        "containers": containers,
        "db_containers": db_containers or [],
    }
    return _post("/api/hosts", json=payload).json()


@mcp.tool()
def regenerate_backup_script(host_id: str) -> dict:
    """Erzwingt eine Neugenerierung des Backup-Scripts fuer einen Host,
    z.B. nachdem Container/Volumes in der Konfiguration geaendert wurden."""
    return _post(f"/api/hosts/{host_id}/regenerate").json()


@mcp.tool()
def get_backup_script(host_id: str) -> str:
    """Liefert das aktuell generierte Bash-Backup-Script (full_backup_<HOST_ID>.sh)
    fuer einen Host als Text (z.B. zur Ueberpruefung oder manuellem Deployment)."""
    return _get(f"/script/{host_id}").text


@mcp.tool()
def get_bootstrap_script(host_id: str) -> str:
    """Liefert das Bootstrap-Script, das auf einem neuen Server einmalig
    ausgefuehrt wird (holt das Backup-Script, richtet Cron ein, macht Testlauf)."""
    return _get(f"/bootstrap/{host_id}").text


@mcp.tool()
def check_backup_api_health() -> dict:
    """Prueft, ob die hAI.BackupServer-API erreichbar ist."""
    return _get("/api/health").json()


if __name__ == "__main__":
    # SSE-Transport: Gateway/Client verbindet sich per URL, z.B.
    # http://<HOST>:8090/sse
    mcp.run(transport="sse")
