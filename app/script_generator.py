"""Rendert Bash-Scripte (Backup, Bootstrap, Enroll) aus Templates."""
import re
import shlex
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

import validation as v
from models import HostConfig

TEMPLATE_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "htm", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["shq"] = lambda value: shlex.quote(str(value))
_env.filters["comment"] = lambda value: re.sub(r"[\r\n]+", " ", str(value))


def render_backup_script(host: HostConfig, cfg: dict, orchestrator_host: str) -> str:
    from confstore import monitoring
    host.validate()
    v.path(cfg.get("nas_base_path", "/mnt/highfishNAS25/Sicherung"))
    mon = monitoring(cfg)
    notif, vers = cfg.get("notifications", {}), cfg.get("versioning", {})
    backup_dir = f"{host.backup_dir_name}/{host.host_name}"
    return _env.get_template("full_backup_template.sh.j2").render(
        host_name=host.host_name, host_id=host.host_id, nas_mount=host.nas_mount,
        nas_base_path=cfg.get("nas_base_path", "/mnt/highfishNAS25/Sicherung"),
        backup_dir_name=host.backup_dir_name,
        require_nas_mount=bool(mon["require_nas_mount"]),
        nas_fstypes=v.fstypes(mon["nas_fstypes"]),
        containers=[{"name": c.name, "paths": c.all_paths()} for c in host.containers],
        db_containers=[{"name": d.name, "db_user": d.db_user} for d in host.db_containers],
        notifications_enabled=bool(notif.get("enabled", False)),
        notification_method=notif.get("method", "ntfy"), ntfy_topic=notif.get("ntfy_topic", ""),
        ntfy_server=notif.get("ntfy_server", ""), email_to=notif.get("email_to", ""),
        versioning_enabled=bool(vers.get("enabled", False)),
        versioning_keep_count=int(vers.get("keep_count", 5)),
        orchestrator_url=f"http://{orchestrator_host}:8080",
        host_token=host.host_token, auto_update=host.auto_update,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def render_bootstrap_script(host: HostConfig, orchestrator_host: str, cron_schedule: str) -> str:
    host.validate()
    v.cron_schedule(cron_schedule)
    return _env.get_template("bootstrap_template.sh.j2").render(
        host_name=host.host_name, host_id=host.host_id, host_token=host.host_token,
        orchestrator_url=f"http://{orchestrator_host}:8080", cron_schedule=cron_schedule)


def render_enroll_script(orchestrator_host: str) -> str:
    text = (TEMPLATE_DIR / "enroll.sh").read_text(encoding="utf-8")
    return text.replace("@@ORCH_URL@@", shlex.quote(f"http://{orchestrator_host}:8080"))
