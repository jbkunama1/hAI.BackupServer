import os
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))


@pytest.fixture
def svc(tmp_path):
    import confstore as cs
    from service import Service
    from store import Store
    (tmp_path / "hosts.yml").write_text(
        "nas_mount_default: highfishNAS25\nnas_base_path: %s\nhosts:\n"
        "  - host_name: highfish5\n    host_id: '5'\n    nas_mount: highfishNAS25\n"
        "    containers:\n      - name: web\n        volume_source_path: /srv/web\n" % (tmp_path / "nas" / "Sicherung"),
        encoding="utf-8")
    return Service(cs.ConfigStore(tmp_path / "hosts.yml"), Store(tmp_path / "t.db"), "192.168.178.26",
                   enroll_token="tok", generated_dir=tmp_path / "gen")
