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
