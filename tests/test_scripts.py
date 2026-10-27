import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

FAKE = {
"docker": r"""#!/bin/bash
args="$*"
case "$1" in
  inspect)
    case "$args" in
      *Mounts*) printf 'bind|%s|/data\nbind|/var/run/docker.sock|/s\nvolume|/nonexistent|/v\ntmpfs||/t\n' "${FAKE_DATA_DIR:-/nonexistent}" ;;
      *Config.Image*) case "${@: -1}" in db) echo postgres:16 ;; *) echo nginx ;; esac ;;
      *) case "${@: -1}" in web|db) exit 0 ;; *) exit 1 ;; esac ;;
    esac ;;
  ps) printf 'web\ndb\nBad Name\n' ;;
  commit|rmi) exit 0 ;;
  save) echo imagedata ;;
  exec) [ -n "${FAKE_DOCKER_EXEC_FAIL:-}" ] && exit 1; echo "dump" ;;
esac
""",
"rsync": r"""#!/bin/bash
[ -n "${FAKE_RSYNC_FAIL:-}" ] && exit 23
mkdir -p "${@: -1}"
""",
"findmnt": r"""#!/bin/bash
case "$*" in *FSTYPE*) echo "${FAKE_FSTYPE:-cifs}" ;; *) echo "${FAKE_MOUNT_TARGET:-/mnt/nas}" ;; esac
""",
"crontab": "#!/bin/bash\nexit 1\n",
"curl": r"""#!/bin/bash
LOG="${FAKE_LOG_DIR}/curl.log"
out=""; url=""; prev=""
for a in "$@"; do
  case "$a" in @*) [ -f "${a#@}" ] && { cat "${a#@}"; echo; } >> "$LOG" ;; esac
  [ "$prev" = "-o" ] && out="$a"; prev="$a"; url="$a"
done
[ -n "${FAKE_CURL_FAIL:-}" ] && exit 22
case "$url" in
  *api/enroll*) printf 'HOST_ID=neu1\nHOST_TOKEN=abcdefghijklmnopqrstuvwxyz012345\nCRON_SCHEDULE=0 3 * * *\n' ;;
  */script/*) printf '#!/bin/bash\necho script\n' > "$out" ;;
esac
exit 0
""",
}


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for n, c in FAKE.items():
        p = bindir / n
        p.write_text(c)
        p.chmod(0o755)
    logs = tmp_path / "logs"
    logs.mkdir()
    data = tmp_path / "datadir"
    data.mkdir()
    e = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_LOG_DIR=str(logs), FAKE_DATA_DIR=str(data),
             HAI_STATE_DIR=str(tmp_path / "state"), HAI_LOGFILE=str(tmp_path / "backup.log"),
             HAI_TARGET_DIR=str(tmp_path / "opt"), HAI_CRON_DIR=str(tmp_path / "cron"), HAI_SKIP_ROOT_CHECK="1")
    return e, tmp_path


def reports(tmp_path):
    f = tmp_path / "logs" / "curl.log"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text().splitlines() if x.startswith("{")]


def make_script(svc, tmp_path, extra=None):
    svc.config.update(lambda cfg: cfg["hosts"][0].update({"containers": [
        {"name": "web", "volume_source_path": None, "volume_paths": [str(tmp_path / "datadir"), "/srv/it's a $dir"]},
        {"name": "ghost", "volume_paths": []}], "db_containers": [{"name": "db", "db_user": "postgres"}]}))
    text = svc.render_script("5")
    p = tmp_path / "backup.sh"
    p.write_text(text)
    p.chmod(0o700)
    return p, text


def test_generated_scripts_have_valid_syntax_and_quoting(svc, tmp_path):
    p, text = make_script(svc, tmp_path)
    assert subprocess.run(["bash", "-n", str(p)]).returncode == 0
    assert "'/srv/it'\"'\"'s a $dir'" in text               # sicher gequotet
    boot = tmp_path / "boot.sh"
    boot.write_text(svc.render_bootstrap("5"))
    assert subprocess.run(["bash", "-n", str(boot)]).returncode == 0
    assert "BASIC_AUTH" not in text and "admin" not in text   # kein Admin-Passwort im Client-Script
    enr = tmp_path / "enroll.sh"
    enr.write_text(svc.render_enroll())
    assert subprocess.run(["bash", "-n", str(enr)]).returncode == 0


def test_run_with_missing_container_is_warning_not_ok(svc, env):
    e, tmp = env
    p, _ = make_script(svc, tmp)
    e["FAKE_MOUNT_TARGET"] = "/mnt/nas"
    r = subprocess.run(["bash", str(p)], env=e, capture_output=True, text=True)
    reps = reports(tmp)
    assert r.returncode == 1 or r.returncode == 0
    statuses = [x["status"] for x in reps]
    assert statuses[0] == "running" and statuses[-1] in ("warning", "error")
    # /srv/it's a $dir existiert nicht -> echter Fehler; ghost fehlt -> Warnung
    assert statuses[-1] == "error" and "ghost" in reps[-1]["message"]
    assert r.returncode == 1


def test_clean_run_reports_ok_and_creates_backup(svc, env):
    e, tmp = env
    svc.config.update(lambda cfg: cfg["hosts"][0].update({"containers": [
        {"name": "web", "volume_source_path": None, "volume_paths": [str(tmp / "datadir")]}], "db_containers": []}))
    p = tmp / "b.sh"
    p.write_text(svc.render_script("5"))
    r = subprocess.run(["bash", str(p)], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    reps = reports(tmp)
    assert [x["status"] for x in reps] == ["running", "ok"] and reps[0]["run_id"] == reps[1]["run_id"]
    nas = Path(svc.cfg()["nas_base_path"]) / "highfish5" / "current"
    assert (nas / "web_image_").parent.exists() and list(nas.glob("web_image_*.tar.gz"))
    assert not list((tmp / "state" / "5" / "spool").glob("*.json"))   # Spool nach Zustellung leer


def test_no_nas_mount_fails_fast_and_reports_error(svc, env):
    e, tmp = env
    e["FAKE_MOUNT_TARGET"] = "/"
    p, _ = make_script(svc, tmp)
    r = subprocess.run(["bash", str(p)], env=e, capture_output=True, text=True)
    assert r.returncode == 2
    assert reports(tmp)[-1]["status"] == "error" and "NAS-Mount" in reports(tmp)[-1]["message"]
    assert not (Path(svc.cfg()["nas_base_path"]) / "highfish5").exists()      # kein Fallback auf lokale Platte


def test_unreachable_server_keeps_exit_code_and_spools(svc, env):
    e, tmp = env
    e["FAKE_CURL_FAIL"] = "1"
    svc.config.update(lambda cfg: cfg["hosts"][0].update({"containers": [], "db_containers": []}))
    p = tmp / "b.sh"
    p.write_text(svc.render_script("5"))
    r = subprocess.run(["bash", str(p)], env=e, capture_output=True, text=True)
    assert r.returncode == 0                                              # Backup selbst war erfolgreich
    assert len(list((tmp / "state" / "5" / "spool").glob("*.json"))) >= 1  # Report liegt im Spool
    e.pop("FAKE_CURL_FAIL")
    subprocess.run(["bash", str(p)], env=e, capture_output=True, text=True)
    assert not list((tmp / "state" / "5" / "spool").glob("*.json"))      # nachgereicht


def test_overlapping_run_is_skipped(svc, env):
    e, tmp = env
    svc.config.update(lambda cfg: cfg["hosts"][0].update({"containers": [], "db_containers": []}))
    p = tmp / "b.sh"
    p.write_text(svc.render_script("5"))
    lock = tmp / "state" / "5"
    lock.mkdir(parents=True)
    holder = subprocess.Popen(["bash", "-c", f"exec 9>{lock}/lock; flock -n 9; sleep 5"])
    import time; time.sleep(0.5)
    r = subprocess.run(["bash", str(p)], env=e, capture_output=True, text=True)
    holder.kill()
    assert r.returncode == 0 and "bereits aktiv" in r.stdout and reports(tmp) == []


def test_db_dump_failure_is_error(svc, env):
    e, tmp = env
    e["FAKE_DOCKER_EXEC_FAIL"] = "1"
    svc.config.update(lambda cfg: cfg["hosts"][0].update({"containers": [], "db_containers": [{"name": "db", "db_user": "postgres"}]}))
    p = tmp / "b.sh"
    p.write_text(svc.render_script("5"))
    r = subprocess.run(["bash", str(p)], env=e, capture_output=True, text=True)
    assert r.returncode == 1 and reports(tmp)[-1]["status"] == "error"


def test_bootstrap_is_idempotent_and_uses_token(svc, env):
    e, tmp = env
    b = tmp / "boot.sh"
    b.write_text(svc.render_bootstrap("5"))
    for _ in range(2):
        r = subprocess.run(["bash", str(b)], env=e, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
    cron = list((tmp / "cron").glob("hai-backup-*"))
    assert len(cron) == 1 and cron[0].read_text().count("full_backup_5.sh") == 1
    assert (tmp / "opt" / "full_backup_5.sh").stat().st_mode & 0o777 == 0o700
    assert "X-Host-Token: " in (tmp / "logs" / "curl.log").read_text()    # Header-Datei enthielt das Host-Token
    assert "basic" not in b.read_text().lower()


def test_enroll_dry_run_filters_sensitive_mounts(svc, env):
    e, tmp = env
    s = tmp / "enroll.sh"
    s.write_text(svc.render_enroll())
    r = subprocess.run(["bash", str(s), "--dry-run", "--yes", "--host-name", "testhost"], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads([l for l in r.stdout.splitlines() if l.startswith("{")][0])
    names = [c["name"] for c in payload["containers"]]
    assert names == ["web", "db"] and "Bad Name" not in names           # ungueltiger Name uebersprungen
    assert payload["containers"][0]["volume_paths"] == [str(tmp / "datadir")]   # docker.sock/nicht vorhandene Pfade raus
    assert payload["db_containers"] == [{"name": "db", "db_user": "postgres"}]
    assert "docker.sock" in r.stdout and "sensibel" in r.stdout


def test_enroll_full_flow(svc, env):
    e, tmp = env
    s = tmp / "enroll.sh"
    s.write_text(svc.render_enroll())
    e["ENROLL_TOKEN"] = "geheim"
    r = subprocess.run(["bash", str(s), "--yes", "--host-name", "testhost"], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp / "opt" / "full_backup_neu1.sh").exists()
    assert "0 3 * * * root" in (tmp / "cron" / "hai-backup-neu1").read_text()
    assert "geheim" not in r.stdout + r.stderr                           # Token nie ausgeben
    e["FAKE_CURL_FAIL"] = "1"
    r = subprocess.run(["bash", str(s), "--yes"], env=e, capture_output=True, text=True)
    assert r.returncode == 1 and "Enrollment fehlgeschlagen" in r.stderr


def test_enroll_help_and_unknown_option(svc, env):
    e, tmp = env
    s = tmp / "enroll.sh"
    s.write_text(svc.render_enroll())
    assert subprocess.run(["bash", str(s), "--help"], env=e, capture_output=True, text=True).returncode == 0
    assert subprocess.run(["bash", str(s), "--bogus"], env=e, capture_output=True, text=True).returncode == 2
