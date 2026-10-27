import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

import monitor
import validation as v
from models import HostConfig
from store import Store, now_iso


def run(rid, status="ok", **kw):
    return {"run_id": rid, "status": status, **kw}


def test_validation_rejects_dangerous_input():
    for bad in ["a b", "x;rm", "../x", "", "a" * 40]:
        with pytest.raises(v.ValidationError):
            v.host_id(bad)
    for bad in ["relative", "/etc", "/", "/var/run/docker.sock", "/a/../etc", "/proc/1", "/x\ny"]:
        with pytest.raises(v.ValidationError):
            v.path(bad)
    assert v.path("/mnt/data//x/") == "/mnt/data/x"
    with pytest.raises(v.ValidationError):
        v.cron_schedule("0 3 * * * ; rm -rf /")


def test_run_lifecycle_dedup_and_ordering(tmp_path):
    s = Store(tmp_path / "a.db")
    s.upsert_run("5", run("run-00001", "running"))
    r, new = s.upsert_run("5", run("run-00001", "error", exit_code=2, message="boom"), host_name="h")
    assert new and r["status"] == "error" and r["final"] == 1
    r, new = s.upsert_run("5", run("run-00001", "error", exit_code=2))      # doppelte Zustellung
    assert not new
    r, _ = s.upsert_run("5", run("run-00001", "running"))                    # verspaetetes Start-Signal
    assert r["status"] == "error"
    assert len(s.events_after(0)) == 1
    with pytest.raises(ValueError):
        s.upsert_run("6", run("run-00001", "ok"))


def test_concurrent_writes_keep_all_runs(tmp_path):
    s = Store(tmp_path / "c.db")
    def work(i):
        for j in range(10):
            s.upsert_run(f"h{i % 3}", run(f"run-{i:03d}-{j:03d}", "ok"))
    ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(s.list_runs(limit=500)) == 80


def test_history_is_bounded(tmp_path):
    s = Store(tmp_path / "h.db")
    for i in range(15):
        s.upsert_run("5", run(f"run-{i:05d}", "ok"), history_limit=5)
    assert len(s.list_runs("5")) == 5


def test_legacy_import_keeps_original_and_is_idempotent(tmp_path):
    f = tmp_path / "reports.json"
    f.write_text(json.dumps({"reports": {"5": {"host_id": "5", "status": "ok", "exit_code": 0,
                 "duration_seconds": 10, "size_bytes": 5, "message": "alt", "reported_at": "2026-10-26T20:00:00+00:00"}}}))
    s = Store(tmp_path / "l.db")
    assert s.import_legacy_reports(f) == 1 and s.import_legacy_reports(f) == 0
    assert f.exists() and s.last_run("5")["message"] == "alt"


def host(**kw):
    d = dict(host_name="h", host_id="5", nas_mount="n", created_at=now_iso())
    d.update(kw)
    return HostConfig(**d)


MON = {"expected_interval_hours": 24, "grace_hours": 4, "enroll_grace_hours": 30, "max_run_hours": 12}


def test_state_machine():
    now = datetime.now(timezone.utc)
    iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert monitor.compute_state(host(monitoring_paused=True), None, MON, now)["state"] == "paused"
    # neu eingerichtet: keine Meldung ist (noch) kein Fehler und wird nicht als "nie gelaufen" behauptet
    st = monitor.compute_state(host(), None, MON, now)
    assert st["state"] == "no_report" and not st["overdue"]
    old = host(created_at=iso(now - timedelta(hours=40)))
    assert monitor.compute_state(old, None, MON, now)["state"] == "overdue"
    ok = {"status": "ok", "first_seen_at": iso(now - timedelta(hours=2))}
    assert monitor.compute_state(host(), ok, MON, now)["state"] == "ok"
    stale = {"status": "ok", "first_seen_at": iso(now - timedelta(hours=40))}
    s = monitor.compute_state(host(), stale, MON, now)
    assert s["state"] == "overdue" and s["overdue"]
    err = {"status": "error", "first_seen_at": iso(now - timedelta(hours=40))}
    assert monitor.compute_state(host(), err, MON, now)["state"] == "error"
    hung = {"status": "running", "first_seen_at": iso(now - timedelta(hours=20))}
    assert monitor.compute_state(host(), hung, MON, now)["state"] == "unknown"
    assert monitor.compute_state(host(), {"status": "running", "first_seen_at": iso(now)}, MON, now)["state"] == "running"


def test_service_report_validation_and_isolation(svc):
    assert svc.verify_host_token("5", svc.host("5").host_token)
    assert not svc.verify_host_token("5", "falsch") and not svc.verify_host_token("5", "")
    res = svc.submit_report("5", {"status": "error", "run_id": "run-abcdef01", "exit_code": 3, "message": "x" * 5000})
    assert res["new_error"] and len(res["run"]["message"]) == 2000
    for bad in [{"status": "kaputt"}, {"status": "ok", "run_id": "a b c d e f g h"}, {"status": "ok", "exit_code": "x"}]:
        with pytest.raises(v.ValidationError):
            svc.submit_report("5", bad)


def test_enroll_idempotent_and_does_not_clobber(svc):
    payload = {"host_name": "newhost", "fingerprint": "a" * 32,
               "containers": [{"name": "app", "volume_paths": ["/srv/app", "/etc", "/var/run/docker.sock"]}],
               "db_containers": [{"name": "db", "db_user": "postgres"}]}
    a = svc.enroll(payload)
    b = svc.enroll(dict(payload, containers=[{"name": "other", "volume_paths": []}]))
    assert a["created"] and not b["created"] and a["host_id"] == b["host_id"] and a["host_token"] == b["host_token"]
    assert [c.name for c in svc.host(a["host_id"]).containers] == ["app"]        # nicht ueberschrieben
    assert len(a["rejected_paths"]) == 2
    svc.enroll(dict(payload, containers=[{"name": "other", "volume_paths": []}]), update_config=True)
    assert [c.name for c in svc.host(a["host_id"]).containers] == ["other"]
    c = svc.enroll({"host_name": "newhost", "fingerprint": "b" * 32})
    assert c["host_id"] != a["host_id"]
    with pytest.raises(v.ValidationError):
        svc.enroll({"host_name": "x;y", "fingerprint": "c" * 32})


def test_delete_pause_and_settings(svc):
    svc.set_paused("5", True, "t")
    assert svc.overview()[0]["state"] == "paused"
    svc.update_settings({"expected_interval_hours": "12", "grace_hours": "1", "enroll_grace_hours": "10",
                         "max_run_hours": "6", "history_limit": "50", "require_nas_mount": "on", "nas_fstypes": "cifs nfs4"}, "t")
    assert svc.cfg()["monitoring"]["nas_fstypes"] == "cifs nfs4"
    with pytest.raises(v.ValidationError):
        svc.update_settings({"expected_interval_hours": "-5"}, "t")
    svc.delete_host("5", "t")
    assert svc.overview() == [] and svc.store.list_audit()


def test_legacy_hosts_keep_old_yaml_format(svc):
    """Unveraenderte Alt-Hosts werden ohne neue Container-Felder zurueckgeschrieben."""
    svc.save_host(svc.host("5"), "t")
    c = svc.cfg()["hosts"][0]["containers"][0]
    assert c == {"name": "web", "volume_source_path": "/srv/web"}


def test_old_hosts_yml_without_new_fields_loads(svc):
    h = svc.host("5")
    assert h.host_token and h.created_at and not h.monitoring_paused
    assert h.containers[0].all_paths() == ["/srv/web"]
