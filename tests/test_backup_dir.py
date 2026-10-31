"""Tests fuer den konfigurierbaren Backup-Verzeichnisnamen (backup_dir_name)."""
import json
import subprocess

import pytest

import validation as v
from models import HostConfig
from test_scripts import env  # noqa: F401  (Fixture mit Fake-docker/curl/rsync wiederverwenden)


def test_dir_name_validation():
    for ok in ["Server", "Archive", "prod-1", "a.b", "A", "."]:
        assert v.dir_name(ok) == ok
    for bad in ["..", ".hidden", "a/b", "a b", "", "Server\n", "x" * 64, "../x", "a..b", None, 5]:
        with pytest.raises(v.ValidationError):
            v.dir_name(bad)


def test_host_without_field_defaults_to_server():
    h = HostConfig.from_dict({"host_name": "h", "host_id": "9", "nas_mount": "n"})
    assert h.backup_dir_name == "Server" and h.to_dict()["backup_dir_name"] == "Server"


def test_backup_dir_name_is_persisted_and_validated(svc):
    h = svc.host("5")
    assert h.backup_dir_name == "."                   # Fixture-Host: Altlayout
    h.backup_dir_name = "Archive"
    svc.save_host(h, "t")
    assert svc.host("5").backup_dir_name == "Archive"
    assert svc.cfg()["hosts"][0]["backup_dir_name"] == "Archive"
    h.backup_dir_name = ".."
    with pytest.raises(v.ValidationError):
        svc.save_host(h, "t")
    assert svc.host("5").backup_dir_name == "Archive"


def test_generated_script_uses_backup_dir(svc):
    a = svc.enroll({"host_name": "newhost", "fingerprint": "a" * 32})
    text = svc.render_script(a["host_id"])
    assert "BACKUP_DIR_NAME=Server" in text
    assert 'BACKUP_DEST="${NAS_BASE_PATH}/${BACKUP_DIR_NAME}/${HOSTNAME_CFG}"' in text
    h = svc.host(a["host_id"])
    h.backup_dir_name = "Archive"
    svc.save_host(h, "t")
    assert "BACKUP_DIR_NAME=Archive" in svc.render_script(a["host_id"])


def test_enroll_service_default_custom_and_hostile(svc):
    base = {"host_name": "newhost", "fingerprint": "a" * 32}
    a = svc.enroll(base)
    assert svc.host(a["host_id"]).backup_dir_name == "Server"
    b = svc.enroll(dict(base, host_name="other", fingerprint="b" * 32, backup_dir_name="Archive"))
    assert svc.host(b["host_id"]).backup_dir_name == "Archive"
    with pytest.raises(v.ValidationError):
        svc.enroll(dict(base, host_name="evil", fingerprint="c" * 32, backup_dir_name=".."))
    assert len(svc.cfg()["hosts"]) == 3


def test_enroll_script_backup_dir_option(svc, env):  # noqa: F811
    e, tmp = env
    s = tmp / "enroll.sh"
    s.write_text(svc.render_enroll())

    def dry(*args, **extra):
        r = subprocess.run(["bash", str(s), "--dry-run", "--yes", "--host-name", "testhost", *args],
                           env=dict(e, **extra), capture_output=True, text=True)
        lines = [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]
        return r, (lines[0] if lines else None)

    r, p = dry()
    assert r.returncode == 0 and "backup_dir_name" not in p       # nichts gesendet -> Server-Standard
    r, p = dry("--backup-dir", "Archive")
    assert r.returncode == 0 and p["backup_dir_name"] == "Archive"
    r, p = dry("--backup-dir", ".")
    assert r.returncode == 0 and p["backup_dir_name"] == "."
    r, p = dry(HAI_BACKUP_DIR_NAME="Prod")
    assert r.returncode == 0 and p["backup_dir_name"] == "Prod"
    for bad in ["..", "a/b", ".hidden", "a b", "x" * 64]:
        r, p = dry("--backup-dir", bad)
        assert r.returncode == 1 and p is None and "Backup-Verzeichnisname" in r.stderr
