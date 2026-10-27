"""hosts.yml: atomares, gesperrtes Lesen/Schreiben und Host-Helfer."""
import copy
import os
import secrets
import shutil
import threading
from pathlib import Path
from typing import List, Optional

import yaml

from models import HostConfig
from store import now_iso

MONITORING_DEFAULTS = {
    "expected_interval_hours": 24,
    "grace_hours": 4,
    "enroll_grace_hours": 30,
    "max_run_hours": 12,
    "history_limit": 200,
    "require_nas_mount": True,
    "nas_fstypes": "",
}

DEFAULT_CFG = {
    "nas_mount_default": "highfishNAS25",
    "nas_base_path": "/mnt/highfishNAS25/Sicherung",
    "notifications": {"enabled": False, "method": "ntfy", "ntfy_topic": "hai-backup-alerts",
                      "ntfy_server": "https://ntfy.sh", "email_to": ""},
    "versioning": {"enabled": False, "keep_count": 5},
    "monitoring": dict(MONITORING_DEFAULTS),
    "hosts": [],
}


def monitoring(cfg: dict) -> dict:
    m = dict(MONITORING_DEFAULTS)
    m.update(cfg.get("monitoring") or {})
    return m


class ConfigStore:
    def __init__(self, path, example=None):
        self.path = Path(path)
        self.example = Path(example) if example else None
        self._lock = threading.RLock()

    def load(self) -> dict:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists() and self.example and self.example.exists():
                shutil.copy(self.example, self.path)
            if not self.path.exists():
                return copy.deepcopy(DEFAULT_CFG)
            with open(self.path, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh) or copy.deepcopy(DEFAULT_CFG)

    def save(self, cfg: dict) -> None:
        with self._lock:
            tmp = self.path.with_name(self.path.name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)

    def update(self, fn):
        """Atomares Lesen-Aendern-Schreiben; fn(cfg) darf ein Ergebnis liefern."""
        with self._lock:
            cfg = self.load()
            result = fn(cfg)
            self.save(cfg)
            return result

    def ensure_defaults(self) -> None:
        """Ergaenzt fehlende Tokens/Zeitstempel bei bestehenden Hosts (einmalig)."""
        def fn(cfg):
            changed = False
            for h in cfg.get("hosts") or []:
                if not h.get("host_token"):
                    h["host_token"] = secrets.token_urlsafe(24)
                    changed = True
                if not h.get("created_at"):
                    h["created_at"] = now_iso()
                    changed = True
            return changed
        with self._lock:
            cfg = self.load()
            if fn(cfg):
                self.save(cfg)


def get_hosts(cfg: dict) -> List[HostConfig]:
    return [HostConfig.from_dict(h) for h in cfg.get("hosts") or []]


def find_host(cfg: dict, host_id: str) -> Optional[HostConfig]:
    for h in get_hosts(cfg):
        if h.host_id == str(host_id):
            return h
    return None


def upsert_host(cfg: dict, host: HostConfig) -> None:
    """Speichert Host; bestehendes Token/created_at/fingerprint bleiben erhalten."""
    hosts = cfg.setdefault("hosts", [])
    for i, h in enumerate(hosts):
        if str(h.get("host_id")) == host.host_id:
            host.host_token = host.host_token or h.get("host_token") or secrets.token_urlsafe(24)
            host.created_at = host.created_at or h.get("created_at") or now_iso()
            host.fingerprint = host.fingerprint or h.get("fingerprint") or ""
            hosts[i] = host.to_dict()
            return
    host.host_token = host.host_token or secrets.token_urlsafe(24)
    host.created_at = host.created_at or now_iso()
    hosts.append(host.to_dict())


def delete_host(cfg: dict, host_id: str) -> bool:
    hosts = cfg.get("hosts") or []
    kept = [h for h in hosts if str(h.get("host_id")) != str(host_id)]
    cfg["hosts"] = kept
    return len(kept) != len(hosts)
