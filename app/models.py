"""Datenmodelle fuer hAI.BackupServer (leichtgewichtig, ohne ORM)."""
from dataclasses import dataclass, field
from typing import List, Optional

import validation as v


@dataclass
class ContainerConfig:
    name: str
    volume_source_path: Optional[str] = None      # Altformat (ein Pfad)
    volume_paths: List[str] = field(default_factory=list)

    def all_paths(self) -> List[str]:
        seen, out = set(), []
        for p in ([self.volume_source_path] if self.volume_source_path else []) + list(self.volume_paths):
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def to_dict(self) -> dict:
        """Alt-Hosts bleiben im alten Format (nur name + volume_source_path) lesbar."""
        d = {"name": self.name}
        if self.volume_source_path:
            d["volume_source_path"] = self.volume_source_path
        if self.volume_paths:
            d["volume_paths"] = list(self.volume_paths)
        return d

    @staticmethod
    def from_dict(d: dict) -> "ContainerConfig":
        return ContainerConfig(
            name=d["name"],
            volume_source_path=d.get("volume_source_path") or None,
            volume_paths=list(d.get("volume_paths") or []),
        )


@dataclass
class DbContainerConfig:
    name: str
    db_user: str = "postgres"

    @staticmethod
    def from_dict(d: dict) -> "DbContainerConfig":
        return DbContainerConfig(name=d["name"], db_user=d.get("db_user") or "postgres")


@dataclass
class HostConfig:
    host_name: str
    host_id: str
    nas_mount: str
    backup_dir_name: str = v.DEFAULT_BACKUP_DIR
    containers: List[ContainerConfig] = field(default_factory=list)
    db_containers: List[DbContainerConfig] = field(default_factory=list)
    host_token: str = ""
    fingerprint: str = ""
    created_at: str = ""
    expected_interval_hours: Optional[float] = None
    monitoring_paused: bool = False
    auto_update: bool = False

    def to_dict(self):
        return {
            "host_name": self.host_name,
            "host_id": self.host_id,
            "nas_mount": self.nas_mount,
            "backup_dir_name": self.backup_dir_name,
            "containers": [c.to_dict() for c in self.containers],
            "db_containers": [{"name": d.name, "db_user": d.db_user} for d in self.db_containers],
            "host_token": self.host_token,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "expected_interval_hours": self.expected_interval_hours,
            "monitoring_paused": self.monitoring_paused,
            "auto_update": self.auto_update,
        }

    def public_dict(self):
        d = self.to_dict()
        d.pop("host_token", None)
        d.pop("fingerprint", None)
        return d

    @staticmethod
    def from_dict(data: dict) -> "HostConfig":
        return HostConfig(
            host_name=data["host_name"],
            host_id=str(data["host_id"]),
            nas_mount=data.get("nas_mount", "highfishNAS25"),
            backup_dir_name=str(data.get("backup_dir_name") or v.DEFAULT_BACKUP_DIR),
            containers=[ContainerConfig.from_dict(c) for c in data.get("containers") or []],
            db_containers=[DbContainerConfig.from_dict(d) for d in data.get("db_containers") or []],
            host_token=data.get("host_token") or "",
            fingerprint=data.get("fingerprint") or "",
            created_at=data.get("created_at") or "",
            expected_interval_hours=data.get("expected_interval_hours"),
            monitoring_paused=bool(data.get("monitoring_paused", False)),
            auto_update=bool(data.get("auto_update", False)),
        )

    def validate(self) -> "HostConfig":
        v.host_id(self.host_id)
        v.host_name(self.host_name)
        v.label(self.nas_mount)
        v.dir_name(self.backup_dir_name)
        for c in self.containers:
            v.container_name(c.name)
            c.volume_source_path = v.path(c.volume_source_path) if c.volume_source_path else None
            c.volume_paths = [v.path(p) for p in c.volume_paths]
        for d in self.db_containers:
            v.container_name(d.name)
            v.db_user(d.db_user)
        if self.expected_interval_hours is not None:
            v.number(self.expected_interval_hours, "Erwartetes Intervall (h)", 1, 24 * 31)
        return self
