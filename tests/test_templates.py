from datetime import datetime, timezone

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

import ui
from models import HostConfig
from store import now_iso


@pytest.fixture
def env():
    from script_generator import TEMPLATE_DIR
    e = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape(["html"]))
    ui.register(e)
    return e


def ctx(svc, **extra):
    base = dict(active="dashboard", csrf="tok", orchestrator_host="192.168.178.26", basic_auth_user="admin", enroll_enabled=True)
    base.update(extra)
    return base


def test_all_pages_render_with_real_data(svc, env):
    svc.submit_report("5", {"status": "error", "run_id": "run-xyz-0001", "message": "<script>alert(1)</script>"})
    rows = svc.overview()
    counts = {r["state"]: 1 for r in rows}
    host = svc.host("5")
    out = env.get_template("dashboard.html").render(ctx(svc, rows=rows, counts=counts, nas_base_path="/mnt/x"))
    assert "highfish5" in out and "FEHLER" in out
    mon = env.get_template("monitoring.html").render(ctx(svc, runs=svc.store.list_runs(limit=10), hosts=[host], selected=""))
    assert "&lt;script&gt;" in mon and "<script>alert" not in mon           # XSS-sicher
    det = env.get_template("host_detail.html").render(ctx(svc, host=host, info=rows[0], runs=svc.store.list_runs("5")))
    assert "Endgültig entfernen" in det and 'name="csrf" value="tok"' in det
    form = env.get_template("host_form.html").render(ctx(svc, host=host, action_url="/hosts/5/edit", containers_raw="web;/srv/web", db_containers_raw="", nas_mount_default=""))
    assert "web;/srv/web" in form
    new = env.get_template("host_form.html").render(ctx(svc, host=None, action_url="/hosts/new", containers_raw="", db_containers_raw="", nas_mount_default="n"))
    assert "Neuer Host" in new
    import confstore as cs
    st = env.get_template("settings.html").render(ctx(svc, mon=cs.monitoring(svc.cfg()), bot_seen=None, audit=[], version="2"))
    assert "nicht verbunden" in st
    en = env.get_template("enroll.html").render(ctx(svc, nas_base_path="/mnt/x"))
    assert "enroll.sh" in en and "Enrollment aktiv" in en


def test_hostile_host_name_is_escaped(svc, env):
    h = HostConfig(host_name='x"><img src=x>', host_id="5", nas_mount="n")
    out = env.get_template("host_detail.html").render(ctx(svc, host=h, info=svc.overview()[0], runs=[]))
    assert "<img src=x>" not in out


def test_ui_filters():
    assert ui.human_size(1536) == "1.5 KB" and ui.fmt_dur(3700) == "1 h 1 min" and ui.fmt_ts(None) == "-"
