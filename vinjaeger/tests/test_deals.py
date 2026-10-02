import asyncio

import pytest
from fastapi.testclient import TestClient

from app import claude, deals, main
from app.models import DealCriteria

CRITERIA = {
    "rules": [
        {"colors": ["rød"], "regions": ["Bourgogne"]},
        {"colors": ["rød"], "regions": ["Barolo"], "max_price": 300},
    ],
    "max_price": 400,
}


def deal(wine, price, normal=None, rule=1, score=7, url=None, **kw):
    return {
        "wine": wine, "producer": None, "region": None, "grapes": None, "color": "rød",
        "vintage": 2020, "shop": "Shop", "url": url or f"https://shop.dk/{wine}",
        "price_dkk": price, "normal_price_dkk": normal, "bottle_ml": 750,
        "matched_rule": rule, "why": "Godt køb", "deal_score": score, **kw,
    }


def test_build_request_lists_rules_and_limits():
    c = DealCriteria(**CRITERIA, min_discount=20, notes="gerne modne årgange")
    text = deals.build_request(c)
    assert "Regel 1: type: rød; område: Bourgogne" in text
    assert "Regel 2: type: rød; område: Barolo; max 300 kr." in text
    assert "400 kr." in text and "20 %" in text and "modne årgange" in text


def test_build_request_skips_empty_rules():
    c = DealCriteria(rules=[{}, {"grapes": ["Nebbiolo"]}])
    assert "Regel 1: drue: Nebbiolo" in deals.build_request(c)


def test_normalize_computes_discount_and_sorts_by_score():
    c = DealCriteria(**CRITERIA)
    out = deals.normalize_deals([
        deal("a", 200, normal=250, score=6),
        deal("b", 150, normal=300, score=9),
        deal("c", 180, score=6),
    ], c)
    assert [d.wine for d in out] == ["b", "a", "c"]
    assert out[0].discount_pct == 50
    assert out[2].discount_pct is None


def test_normalize_enforces_price_limits():
    c = DealCriteria(**CRITERIA)
    out = deals.normalize_deals([
        deal("over_general", 450, rule=1),
        deal("over_rule", 350, rule=2),
        deal("ok_rule2", 290, rule=2),
        deal("magnum", 700, rule=1, bottle_ml=1500),  # 350 pr. 75 cl
    ], c)
    assert sorted(d.wine for d in out) == ["magnum", "ok_rule2"]


def test_normalize_min_discount_and_garbage():
    c = DealCriteria(rules=[{"colors": ["hvid"]}], min_discount=20)
    out = deals.normalize_deals([
        deal("lille_rabat", 90, normal=100),
        deal("stor_rabat", 70, normal=100),
        deal("ingen_normalpris", 50),
        deal("", 50),
        deal("bad_url", 50, url="javascript:alert(1)"),
        deal("dublet", 70, normal=100, url="https://shop.dk/stor_rabat/"),
        deal("score", 60, normal=100, score=99, matched_rule=7),
    ], c)
    assert [d.wine for d in out] == ["score", "stor_rabat"]
    assert out[0].deal_score == 10
    assert out[0].matched_rule is None


@pytest.fixture
def client(monkeypatch):
    main.deal_jobs = deals.JobRunner()
    calls = []

    async def fake_agent(system, request, tools, report_tool, effort="medium"):
        calls.append((request, [t.get("name") for t in tools], report_tool, effort))
        await asyncio.sleep(0)
        return {"summary": "To gode fund", "deals": [deal("x", 199, normal=279)]}

    monkeypatch.setattr(claude, "_run_agent", fake_agent)
    c = TestClient(main.app)
    c.calls = calls
    return c


def poll(client, job_id):
    for _ in range(50):
        job = client.get(f"/api/deals/{job_id}").json()
        if job["status"] != "running":
            return job
    raise AssertionError("job blev ikke færdigt")


def test_deal_job_flow_and_cache(client):
    with client:
        job = client.post("/api/deals", json=CRITERIA).json()
        assert job["status"] in ("running", "done")
        done = poll(client, job["id"])
        assert done["status"] == "done"
        assert done["result"]["deals"][0]["discount_pct"] == 29
        assert client.calls[0][1] == ["web_search", "web_fetch", "report_deals"]

        again = client.post("/api/deals", json=CRITERIA).json()
        assert again["result"]["cached"] is True
        assert len(client.calls) == 1

        fresh = client.post("/api/deals?refresh=true", json=CRITERIA).json()
        poll(client, fresh["id"])
        assert len(client.calls) == 2


def test_deal_validation(client):
    assert client.post("/api/deals", json={"rules": []}).status_code == 422
    r = client.post("/api/deals", json={"rules": [{}]})
    assert r.status_code == 422
    assert client.get("/api/deals/findesikke").status_code == 404


def test_deal_job_error(client, monkeypatch):
    async def boom(*a, **k):
        raise claude.ClaudeError("Søgningen blev afvist.")

    monkeypatch.setattr(claude, "_run_agent", boom)
    with client:
        job = client.post("/api/deals", json=CRITERIA).json()
        done = poll(client, job["id"])
    assert done == {"id": job["id"], "status": "error", "result": None, "error": "Søgningen blev afvist."}
