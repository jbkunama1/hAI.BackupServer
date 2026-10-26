"""Datenmodelle fuer hAI.BackupServer (leichtgewichtig, ohne ORM)."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ContainerConfig:
    name: str
    volume_source_path: Optional[str] = None


@dataclass
class DbContainerConfig:
    name: str
    db_user: str = "postgres"


@dataclass
class HostConfig:
    host_name: str
    host_id: str
    nas_mount: str
    containers: List[ContainerConfig] = field(default_factory=list)
    db_containers: List[DbContainerConfig] = field(default_factory=list)

    def to_dict(self):
        return {
            "host_name": self.host_name,
            "host_id": self.host_id,
            "nas_mount": self.nas_mount,
            "containers": [c.__dict__ for c in self.containers],
            "db_containers": [d.__dict__ for d in self.db_containers],
        }

    @staticmethod
    def from_dict(data: dict) -> "HostConfig":
        return HostConfig(
            host_name=data["host_name"],
            host_id=str(data["host_id"]),
            nas_mount=data.get("nas_mount", "highfishNAS25"),
            containers=[ContainerConfig(**c) for c in data.get("containers", [])],
            db_containers=[DbContainerConfig(**d) for d in data.get("db_containers", [])],
        )


@dataclass
class BackupReport:
    """Letzter Ergebnis-Report eines Backup-Laufs (Monitoring)."""

    host_id: str
    status: str                       # "ok" | "error"
    exit_code: int = 0
    duration_seconds: float = 0.0
    size_bytes: int = 0
    message: str = ""
    reported_at: str = ""             # ISO 8601 (UTC)

    def to_dict(self):
        return {
            "host_id": self.host_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "size_bytes": self.size_bytes,
            "message": self.message,
            "reported_at": self.reported_at,
        }

    @staticmethod
    def from_dict(data: dict) -> "BackupReport":
        return BackupReport(
            host_id=str(data["host_id"]),
            status=str(data["status"]),
            exit_code=int(data.get("exit_code", 0)),
            duration_seconds=float(data.get("duration_seconds", 0)),
            size_bytes=int(data.get("size_bytes", 0)),
            message=str(data.get("message", "")),
            reported_at=str(data.get("reported_at", "")),
        )
