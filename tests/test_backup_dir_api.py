"""HTTP-Tests fuer backup_dir_name in Web-UI und API (benoetigen FastAPI; laufen in der CI)."""
from test_api import ADMIN, api  # noqa: F401  (importorskip fuer fastapi/multipart steckt in test_api)


def _form(m, **extra):
    base = {"csrf": m.csrf_token("admin"), "host_name": "alpha", "nas_mount": "n",
            "containers_raw": "", "db_containers_raw": ""}
    base.update(extra)
    return base


def test_ui_form_shows_and_changes_backup_dir(api):  # noqa: F811
    c, m = api
    assert 'name="backup_dir_name"' in c.get("/hosts/a/edit", auth=ADMIN).text
    assert 'value="Server"' in c.get("/hosts/new", auth=ADMIN).text
    r = c.post("/hosts/a/edit", auth=ADMIN, data=_form(m, backup_dir_name="Archive"), follow_redirects=False)
    assert r.status_code == 303 and m.svc.host("a").backup_dir_name == "Archive"
    r = c.post("/hosts/a/edit", auth=ADMIN, data=_form(m, backup_dir_name=".."), follow_redirects=False)
    assert r.status_code == 400 and m.svc.host("a").backup_dir_name == "Archive"


def test_ui_edit_without_field_keeps_backup_dir(api):  # noqa: F811
    c, m = api
    h = m.svc.host("a")
    h.backup_dir_name = "Archive"
    m.svc.save_host(h, "t")
    r = c.post("/hosts/a/edit", auth=ADMIN, data=_form(m), follow_redirects=False)
    assert r.status_code == 303 and m.svc.host("a").backup_dir_name == "Archive"


def test_ui_create_host_defaults_to_server(api):  # noqa: F811
    c, m = api
    r = c.post("/hosts/new", auth=ADMIN, data=_form(m, host_id="neu", host_name="neu"), follow_redirects=False)
    assert r.status_code == 303 and m.svc.host("neu").backup_dir_name == "Server"


def test_api_upsert_keeps_sets_and_validates_backup_dir(api):  # noqa: F811
    c, m = api
    h = m.svc.host("a")
    h.backup_dir_name = "Archive"
    m.svc.save_host(h, "t")
    body = {"host_name": "alpha", "host_id": "a", "nas_mount": "n"}
    assert c.post("/api/hosts", auth=ADMIN, json=body).status_code == 200
    assert m.svc.host("a").backup_dir_name == "Archive"           # nicht mitgeschickt -> bleibt
    assert c.post("/api/hosts", auth=ADMIN, json=dict(body, backup_dir_name="Prod")).status_code == 200
    assert m.svc.host("a").backup_dir_name == "Prod"
    assert c.post("/api/hosts", auth=ADMIN, json=dict(body, backup_dir_name="..")).status_code == 400
    assert c.get("/api/hosts/a", auth=ADMIN).json()["backup_dir_name"] == "Prod"
