"""HTTP-Tests (benoetigen FastAPI; laufen in der CI, lokal nur wenn installiert)."""
import sys

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("multipart")
from fastapi.testclient import TestClient  # noqa: E402

ADMIN = ("admin", "pw")


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("GENERATED_DIR", str(tmp_path / "gen"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "pw")
    monkeypatch.setenv("ENROLL_TOKEN", "tok-enroll-7x")
    (tmp_path / "hosts.yml").write_text("nas_base_path: /mnt/x/S\nhosts:\n  - host_name: alpha\n    host_id: a\n    nas_mount: n\n"
                                        "  - host_name: beta\n    host_id: b\n    nas_mount: n\n", encoding="utf-8")
    sys.modules.pop("main", None)
    import main
    return TestClient(main.app), main


def tok(main, hid):
    return main.svc.host(hid).host_token


def test_admin_required_everywhere(api):
    c, _ = api
    for path in ["/", "/api/hosts", "/api/status", "/settings", "/monitoring", "/bootstrap/a"]:
        assert c.get(path).status_code == 401
    assert c.get("/api/hosts", auth=("admin", "falsch")).status_code == 401
    assert c.get("/api/hosts", auth=ADMIN).status_code == 200


def test_host_token_is_scoped_to_own_host(api):
    c, m = api
    h = {"X-Host-Token": tok(m, "a")}
    assert c.post("/api/hosts/a/report", json={"status": "ok", "run_id": "run-aaaa-0001"}, headers=h).status_code == 200
    assert c.post("/api/hosts/b/report", json={"status": "ok", "run_id": "run-bbbb-0001"}, headers=h).status_code == 403
    assert c.get("/script/b", headers=h).status_code == 403
    assert c.get("/script/a", headers=h).status_code == 200
    assert c.get("/api/hosts", headers=h).status_code == 401           # kein Admin-Zugriff mit Host-Token


def test_report_to_event_and_status(api):
    c, m = api
    h = {"X-Host-Token": tok(m, "a")}
    c.post("/api/hosts/a/report", json={"status": "running", "run_id": "run-aaaa-0002"}, headers=h)
    c.post("/api/hosts/a/report", json={"status": "error", "run_id": "run-aaaa-0002", "exit_code": 2, "message": "kaputt"}, headers=h)
    c.post("/api/hosts/a/report", json={"status": "error", "run_id": "run-aaaa-0002", "exit_code": 2}, headers=h)   # Duplikat
    ev = c.get("/api/events", auth=ADMIN, headers={"X-Actor": "telegram:1"}).json()["events"]
    assert len(ev) == 1 and ev[0]["payload"]["message"] == "kaputt"
    assert c.get("/api/status", auth=ADMIN).json()["counts"]["error"] == 1
    assert c.post("/api/hosts/a/report", json={"status": "kaputt"}, headers=h).status_code == 400


def test_api_never_leaks_tokens(api):
    c, m = api
    assert "host_token" not in c.get("/api/hosts", auth=ADMIN).text
    assert tok(m, "a") not in c.get("/api/hosts/a", auth=ADMIN).text


def test_enroll_requires_token_and_is_idempotent(api):
    c, m = api
    body = {"host_name": "gamma", "fingerprint": "e" * 32, "containers": [{"name": "app", "volume_paths": ["/srv/app"]}]}
    assert c.post("/api/enroll", json=body).status_code == 403
    assert c.post("/api/enroll", json=body, headers={"X-Enroll-Token": "falsch"}).status_code == 403
    r1 = c.post("/api/enroll?format=env", json=body, headers={"X-Enroll-Token": "tok-enroll-7x"})
    r2 = c.post("/api/enroll?format=env", json=body, headers={"X-Enroll-Token": "tok-enroll-7x"})
    assert r1.status_code == 200 and r1.text == r2.text and "HOST_TOKEN=" in r1.text
    m.ENROLL_TOKEN = ""
    assert c.post("/api/enroll", json=body, headers={"X-Enroll-Token": ""}).status_code == 503
    assert "tok-enroll-7x" not in c.get("/enroll.sh").text


def test_csrf_and_confirmation_for_delete(api):
    c, m = api
    assert c.post("/hosts/b/delete", auth=ADMIN, data={"confirm": "b"}).status_code == 403
    good = m.csrf_token("admin")
    assert c.post("/hosts/b/delete", auth=ADMIN, data={"csrf": good, "confirm": "x"}).status_code == 400
    r = c.post("/hosts/b/delete", auth=ADMIN, data={"csrf": good, "confirm": "b"}, follow_redirects=False)
    assert r.status_code == 303 and c.get("/api/hosts/b", auth=ADMIN).status_code == 404
    assert c.get("/hosts/b/delete", auth=ADMIN).status_code == 405        # kein Schreiben per GET


def test_mutating_json_endpoint_needs_xhr_header(api):
    c, _ = api
    assert c.post("/api/hosts/a/pause", auth=ADMIN, json={"paused": True}).status_code == 400
    assert c.post("/api/hosts/a/pause", auth=ADMIN, json={"paused": True}, headers={"X-Requested-With": "x"}).status_code == 200


def test_pages_render(api):
    c, _ = api
    for path in ["/", "/monitoring", "/enroll", "/settings", "/hosts/new", "/hosts/a", "/hosts/a/edit"]:
        r = c.get(path, auth=ADMIN)
        assert r.status_code == 200, path
