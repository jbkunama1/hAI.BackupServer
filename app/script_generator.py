"""Rendert aus den Jinja2-Templates fertige Bash-Scripte pro Host."""
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from models import HostConfig

TEMPLATE_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(disabled_extensions=("sh.j2",)),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_backup_script(
    host: HostConfig,
    nas_base_path: str,
    notifications_enabled: bool,
    notification_method: str,
    ntfy_topic: str,
    ntfy_server: str,
    email_to: str,
    versioning_enabled: bool,
    versioning_keep_count: int,
    orchestrator_host: str,
) -> str:
    template = _env.get_template("full_backup_template.sh.j2")
    return template.render(
        host_name=host.host_name,
        host_id=host.host_id,
        nas_mount=host.nas_mount,
        nas_base_path=nas_base_path,
        containers=[c.__dict__ for c in host.containers],
        db_containers=[d.__dict__ for d in host.db_containers],
        notifications_enabled=notifications_enabled,
        notification_method=notification_method,
        ntfy_topic=ntfy_topic,
        ntfy_server=ntfy_server,
        email_to=email_to,
        versioning_enabled=versioning_enabled,
        versioning_keep_count=versioning_keep_count,
        orchestrator_host=orchestrator_host,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def render_bootstrap_script(
    host: HostConfig,
    orchestrator_host: str,
    cron_schedule: str = "0 3 * * *",
    basic_auth_user: str = "admin",
    basic_auth_password: str = "",
) -> str:
    template = _env.get_template("bootstrap_template.sh.j2")
    return template.render(
        host_name=host.host_name,
        host_id=host.host_id,
        orchestrator_host=orchestrator_host,
        cron_schedule=cron_schedule,
        basic_auth_user=basic_auth_user,
        basic_auth_password=basic_auth_password,
    )
