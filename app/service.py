"""Geschaeftslogik (framework-frei, daher unabhaengig von FastAPI testbar)."""
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import confstore as cs
import monitor
import script_generator as sg
import validation as v
from models import ContainerConfig, DbContainerConfig, HostConfig
from store import Store, now_iso, parse_iso

REPORT_STATUS = {"running", "ok", "warning", "error"}


class NotFound(LookupError):
    pass


class Service:
    def __init__(self, config: cs.ConfigStore, store: Store, orchestrator_host: str,
                 cron_schedule: str = "0 3 * * *", enroll_token: str = "", generated_dir=None):
        self.config, self.store = config, store
        self.orchestrator_host = orchestrator_host
        self.cron_schedule = v.cron_schedule(cron_schedule)
        self.enroll_token = enroll_token
        self.generated_dir = Path(generated_dir) if generated_dir else None
        self.config.ensure_defaults()
        legacy = self.config.path.parent / "reports.json"
        if legacy.exists():
            self.store.import_legacy_reports(legacy)

    # ---- Lesen -----------------------------------------------------------
    def cfg(self) -> dict:
        return self.config.load()

    def host(self, host_id: str) -> HostConfig:
        h = cs.find_host(self.cfg(), host_id)
        if not h:
            raise NotFound(f"Host-ID {host_id} nicht konfiguriert")
        return h

    def verify_host_token(self, host_id: str, token: str) -> bool:
        h = cs.find_host(self.cfg(), host_id)
        return bool(h and token and h.host_token and secrets.compare_digest(h.host_token, token))

    # ---- Scripte ---------------------------------------------------------
    def render_script(self, host_id: str) -> str:
        return sg.render_backup_script(self.host(host_id), self.cfg(), self.orchestrator_host)

    def regenerate(self, host_id: str) -> str:
        text = self.render_script(host_id)
        if self.generated_dir:
            self.generated_dir.mkdir(parents=True, exist_ok=True)
            p = self.generated_dir / f"full_backup_{host_id}.sh"
            p.write_text(text, encoding="utf-8")
            return str(p)
        return ""

    def render_bootstrap(self, host_id: str) -> str:
        return sg.render_bootstrap_script(self.host(host_id), self.orchestrator_host, self.cron_schedule)

    def render_enroll(self) -> str:
        return sg.render_enroll_script(self.orchestrator_host)

    # ---- Hosts verwalten ------------------------------------------------
    @staticmethod
    def parse_containers(raw: str) -> List[ContainerConfig]:
        out = []
        for line in (raw or "").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(";")]
            paths = [p for p in parts[1:] if p]
            out.append(ContainerConfig(name=parts[0], volume_paths=paths))
        return out

    @staticmethod
    def parse_db_containers(raw: str) -> List[DbContainerConfig]:
        out = []
        for line in (raw or "").splitlines():
            line = line.strip()
            if line:
                parts = [p.strip() for p in line.split(";")]
                out.append(DbContainerConfig(name=parts[0], db_user=(parts[1] if len(parts) > 1 and parts[1] else "postgres")))
        return out

    def save_host(self, host: HostConfig, actor: str, create_only: bool = False) -> HostConfig:
        host.validate()

        def fn(cfg):
            exists = cs.find_host(cfg, host.host_id)
            if create_only and exists:
                raise v.ValidationError(f"Host-ID {host.host_id} existiert bereits.")
            if exists:   # Server-verwaltete Felder behalten
                host.host_token, host.fingerprint = exists.host_token, exists.fingerprint
                host.created_at, host.monitoring_paused = exists.created_at, exists.monitoring_paused
            cs.upsert_host(cfg, host)
        self.config.update(fn)
        self.store.audit(actor, "host_save", host.host_id)
        return self.host(host.host_id)

    def set_paused(self, host_id: str, paused: bool, actor: str) -> None:
        def fn(cfg):
            for h in cfg.get("hosts") or []:
                if str(h.get("host_id")) == host_id:
                    h["monitoring_paused"] = bool(paused)
                    return True
            raise NotFound(f"Host-ID {host_id} nicht konfiguriert")
        self.config.update(fn)
        self.store.audit(actor, "monitoring_pause" if paused else "monitoring_resume", host_id)

    def delete_host(self, host_id: str, actor: str) -> None:
        if not self.config.update(lambda cfg: cs.delete_host(cfg, host_id)):
            raise NotFound(f"Host-ID {host_id} nicht konfiguriert")
        if self.generated_dir:
            (self.generated_dir / f"full_backup_{host_id}.sh").unlink(missing_ok=True)
        self.store.audit(actor, "host_delete", host_id, "nur Konfiguration; Backups und Client-Cron bleiben bestehen")

    def update_settings(self, form: dict, actor: str) -> None:
        mon = {
            "expected_interval_hours": v.number(form.get("expected_interval_hours"), "Intervall", 1, 744, 24),
            "grace_hours": v.number(form.get("grace_hours"), "Karenz", 0, 168, 4),
            "enroll_grace_hours": v.number(form.get("enroll_grace_hours"), "Einrichtungsfrist", 1, 744, 30),
            "max_run_hours": v.number(form.get("max_run_hours"), "Maximale Laufzeit", 1, 168, 12),
            "history_limit": int(v.number(form.get("history_limit"), "Historie", 10, 5000, 200)),
            "require_nas_mount": bool(form.get("require_nas_mount")),
            "nas_fstypes": v.fstypes(form.get("nas_fstypes", "")).strip(),
        }
        self.config.update(lambda cfg: cfg.__setitem__("monitoring", mon))
        self.store.audit(actor, "settings_update", "monitoring")

    # ---- Enrollment ------------------------------------------------------
    def enroll(self, payload: dict, update_config: bool = False) -> dict:
        fpr = v.fingerprint(str(payload.get("fingerprint", "")))
        name = v.host_name(str(payload.get("host_name", "")))
        backup_dir_name = v.label(str(payload.get("backup_dir_name", "Server")))
            samba_share_path = None
            if payload.get("samba_share_path"):
                samba_share_path = v.samba_share_path(str(payload.get("samba_share_path")))
            samba_username = None
            if payload.get("samba_username"):
                samba_username = v.samba_username(str(payload.get("samba_username")))
            samba_password = None
            if payload.get("samba_password"):
                samba_password = v.samba_password(str(payload.get("samba_password")))
            containers, rejected = [], []
            for c in payload.get("containers") or []:
                try:
                    paths = []
                    for p in c.get("volume_paths") or []:
                        try:
                            paths.append(v.path(p))
                        except v.ValidationError:
                            rejected.append(str(p)[:200])
                    containers.append(ContainerConfig(name=v.container_name(c.get("name")), volume_paths=paths))
                except (v.ValidationError, AttributeError):
                    rejected.append(str(c)[:200])
            dbs = []
            for d in payload.get("db_containers") or []:
                dbs.append(DbContainerConfig(name=v.container_name(d.get("name")), db_user=v.db_user(d.get("db_user") or "postgres")))
            mon_nas = self.cfg().get("nas_mount_default", "highfishNAS25")

            def fn(cfg):
                hosts = cfg.setdefault("hosts", [])
                for h in hosts:
                    if h.get("fingerprint") == fpr:
                        changed = False
                        if update_config:
                            h["host_name"] = name
                            h["backup_dir_name"] = backup_dir_name
                            h["samba_share_path"] = samba_share_path
                            h["samba_username"] = samba_username
                            h["samba_password"] = samba_password
                            h["containers"] = [c.to_dict() for c in containers]
                            h["db_containers"] = [{"name": d.name, "db_user": d.db_user} for d in dbs]
                            changed = True
                        return h["host_id"], h["host_token"], False, changed
                taken = {str(h.get("host_id")) for h in hosts}
                base, hid, n = v.slug(name), v.slug(name), 2
                while hid in taken:
                    hid = f"{base[:28]}-{n}"
                    n += 1
                token = secrets.token_urlsafe(24)
                host = HostConfig(host_name=name, host_id=hid, nas_mount=mon_nas, backup_dir_name=backup_dir_name,
                                 samba_share_path=samba_share_path, samba_username=samba_username, samba_password=samba_password,
                                 containers=containers, db_containers=dbs, host_token=token, fingerprint=fpr, created_at=now_iso())
                hosts.append(host.validate().to_dict())
                return hid, token, True, True
            hid, token, created, changed = self.config.update(fn)
            self.store.audit("enroll", "host_enroll", hid, f"created={created} config_updated={changed} rejected={len(rejected)}")
        return {"host_id": hid, "host_token": token, "created": created, "config_updated": changed,
                "cron_schedule": self.cron_schedule, "rejected_paths": rejected}

    # ---- Monitoring ------------------------------------------------------
    @staticmethod
    def clean_report(p: dict) -> dict:
        if not isinstance(p, dict):
            raise v.ValidationError("Report muss ein JSON-Objekt sein")
        status = str(p.get("status", "")).lower()
        if status not in REPORT_STATUS:
            raise v.ValidationError("status muss running, ok, warning oder error sein")
        rid = p.get("run_id") or f"auto-{time.time_ns()}"
        started = p.get("started_at")
        return {
            "run_id": v.run_id(str(rid)), "status": status,
            "exit_code": int(v.number(p.get("exit_code"), "exit_code", -255, 255, 0)),
            "duration_seconds": v.number(p.get("duration_seconds"), "duration_seconds", 0, 1e7, 0),
            "size_bytes": int(v.number(p.get("size_bytes"), "size_bytes", 0, 1e15, 0)),
            "warnings": int(v.number(p.get("warnings"), "warnings", 0, 100000, 0)),
            "started_at": started if parse_iso(started) else None,
            "message": str(p.get("message", ""))[:2000],
        }

    def submit_report(self, host_id: str, payload: dict) -> dict:
        host = self.host(host_id)
        data = self.clean_report(payload)
        limit = int(cs.monitoring(self.cfg())["history_limit"])
        try:
            run, new_error = self.store.upsert_run(host_id, data, history_limit=limit, host_name=host.host_name)
        except ValueError as e:
            raise v.ValidationError(str(e))
        return {"run": run, "new_error": new_error}

    def overview(self, now: Optional[datetime] = None) -> List[dict]:
        cfg = self.cfg()
        mon = cs.monitoring(cfg)
        latest = self.store.latest_per_host()
        out = []
        for h in cs.get_hosts(cfg):
            last = latest.get(h.host_id)
            st = monitor.compute_state(h, last, mon, now)
            ok = self.store.last_success(h.host_id)
            out.append({"host": h.public_dict(), "host_obj": h, "last": last,
                        "last_success_at": ok["first_seen_at"] if ok else None,
                        "label": monitor.STATE_LABELS[st["state"]], "pill": monitor.pill_class(st["state"]), **st})
        return out

    def status(self, now: Optional[datetime] = None) -> dict:
        rows = self.overview(now)
        counts = {}
        for r in rows:
            counts[r["state"]] = counts.get(r["state"], 0) + 1
        slim = [{k: r[k] for k in ("state", "label", "overdue", "detail", "interval_hours", "last", "last_success_at")}
                | {"host_id": r["host"]["host_id"], "host_name": r["host"]["host_name"],
                   "paused": r["host"]["monitoring_paused"]} for r in rows]
        return {"generated_at": now_iso(), "counts": counts, "hosts": slim}

    def digest(self, hours: float = 24, now: Optional[datetime] = None) -> dict:
        st = self.status(now)
        since = (now or datetime.now(timezone.utc)) - timedelta(hours=hours)
        runs = [r for r in self.store.list_runs(limit=500) if (parse_iso(r["first_seen_at"]) or since) >= since]
        st["runs_in_window"] = len(runs)
        st["attention"] = [h for h in st["hosts"] if h["state"] in ("error", "overdue", "no_report", "unknown", "warning")]
        st["hours"] = hours
        return st
