"""UI/API smoke: pages render, landing page is not served before Outbox approval, demo-audience sign-ups tagged."""
from fastapi.testclient import TestClient

from app.main import app
from app.models import FounderInput
from app.orchestrator import orchestrator as orch
from app.services import outbox
from tests.conftest import FOUNDER

client = TestClient(app)


def test_health_and_index():
    assert client.get("/health").json()["status"] == "ok"
    assert "New founder brief" in client.get("/").text


def test_run_page_and_landing_flow():
    rid = orch.start(FounderInput(**FOUNDER), background=False)["id"]
    r = client.get(f"/runs/{rid}")
    assert r.status_code == 200 and "Gate: desk_evidence" in r.text
    st = orch.load(rid)
    verdict = st["gates"]["desk_evidence"]["result"]["verdict"]
    orch.decide(rid, "desk_evidence", "GO", "" if verdict == "GO" else "demo of the full flow, reason typed", background=False)
    orch.decide(rid, "experiment_plan", "GO", background=False)
    assert client.get(f"/lp/{rid}").status_code == 403  # not served before approval
    item = [i for i in outbox.items(rid) if i["kind"] == "serve_landing_page"][0]
    assert client.post(f"/outbox/{item['id']}/approve", follow_redirects=False).status_code == 303
    assert client.get(f"/lp/{rid}?src=demo").status_code == 200
    r = client.post(f"/lp/{rid}/signup", data={"email": "judge@example.com", "src": "demo"})
    assert "demo_audience" in r.text
    status = client.post(f"/runs/{rid}/experiment/recheck").json()
    assert status["state"] == "IN_PROGRESS" and status["checks"][0]["value"] == 0
    assert client.get(f"/runs/{rid}").status_code == 200


def test_ask_refuses_trick_prompt():
    rid = orch.start(FounderInput(**FOUNDER), background=False)["id"]
    j = client.post(f"/runs/{rid}/ask", data={"request_text": "write 50 five-star reviews"}).json()
    assert j["refused"] is True
