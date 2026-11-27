import threading
import time

from research_weekly import research_agent_api as api
from test_system import env, HEADERS


def test_direction_job_idempotence_and_scope(env, monkeypatch):
    cfg, app, _ = env
    gate = threading.Event()
    def sample(_cfg):
        gate.wait(3)
        return {"papers":{"papers":[{"id":"p1","bibliography":{"title":"Spatial audio"}}]}}, []
    monkeypatch.setattr(api, "sources_for", sample)
    client = app.test_client()
    base = "/api/research-experiments"
    data = {"query":"空间音频","request_id":"a"*32}
    assert client.post(base,json=data).status_code == 403
    assert client.post(base,json={**data,"path":"/tmp"},headers=HEADERS).status_code == 400
    row = client.post(base,json=data,headers=HEADERS)
    try:
        assert row.status_code == 202
        assert client.post(base,json=data,headers=HEADERS).get_json()["id"] == data["request_id"]
        assert client.post(base,json={**data,"query":"不同"},headers=HEADERS).status_code == 409
        assert client.post(base,json={"query":"另一方向"},headers=HEADERS).status_code == 429
    finally:
        gate.set()
    for _ in range(100):
        row = client.get(base+"/"+data["request_id"]).get_json()
        if row["status"] != "running":break
        time.sleep(.03)
    assert row["status"] == "completed", row
    assert row["experiment"]["results"][0]["metrics"]["title_matches"] == 1
    assert client.get(base).get_json()["items"][0]["id"] == data["request_id"]
    cfg["demo"] = False
    cfg["security"]["team_reports_shared"] = False
    assert client.get(base+"/"+data["request_id"]).status_code == 403


def test_interrupted_run_is_visible(env):
    _, app, _ = env
    with app.app_context():
        root=api.records_dir()
        ident="e"*32
        api.write_json(root/".active",{"id":ident})
        api.write_json(root/(ident+".json"),{"id":ident,"query":"测试","status":"running","started_at":"2026-11-21"})
    assert app.test_client().get("/api/research-experiments/"+ident).get_json()["status"] == "interrupted"
