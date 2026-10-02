from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import claude, main
from app.models import WineIdentity

RAW = {
    "summary": "Fundet hos to forhandlere.",
    "offers": [
        {"shop": "Dyr", "url": "https://dyr.dk/v", "price_dkk": 249.95, "bottle_ml": 750,
         "vintage": 2019, "in_stock": True, "note": None},
        {"shop": "Billig", "url": "https://billig.dk/v", "price_dkk": 199.0, "bottle_ml": 750,
         "vintage": 2019, "in_stock": True, "note": "v. køb af 6"},
    ],
}


@pytest.fixture
def client(monkeypatch):
    main.cache._data.clear()
    calls = []

    async def fake_find(q, vintage=None, ean=None):
        calls.append((q, vintage, ean))
        return RAW

    monkeypatch.setattr(claude, "find_offers", fake_find)
    c = TestClient(main.app)
    c.calls = calls
    return c


def test_search_returns_cheapest_and_caches(client):
    r = client.get("/api/search", params={"q": "Musar", "vintage": 2019})
    assert r.status_code == 200
    body = r.json()
    assert body["cheapest"]["shop"] == "Billig"
    assert [o["shop"] for o in body["offers"]] == ["Billig", "Dyr"]
    assert body["cached"] is False

    again = client.get("/api/search", params={"q": "musar", "vintage": 2019}).json()
    assert again["cached"] is True
    assert len(client.calls) == 1


def test_search_validates_ean(client):
    assert client.get("/api/search", params={"q": "x y", "ean": "abc"}).status_code == 422


def test_token_required_when_configured(client, monkeypatch):
    monkeypatch.setattr(main, "ACCESS_TOKEN", "hemmelig")
    assert client.get("/api/search", params={"q": "Musar"}).status_code == 401
    ok = client.get("/api/search", params={"q": "Musar"}, headers={"X-Vinjaeger-Token": "hemmelig"})
    assert ok.status_code == 200


def test_claude_error_is_shown(client, monkeypatch):
    async def boom(*a, **k):
        raise claude.ClaudeError("Søgningen blev afvist.")

    monkeypatch.setattr(claude, "find_offers", boom)
    r = client.get("/api/search", params={"q": "Musar"})
    assert r.status_code == 502
    assert r.json()["detail"] == "Søgningen blev afvist."


def test_identify(client, monkeypatch):
    async def fake_identify(data, media_type):
        assert media_type == "image/jpeg"
        return WineIdentity(producer="Château Musar", wine_name="Rouge", vintage=2017,
                            search_query="Château Musar Rouge", confidence=0.9)

    monkeypatch.setattr(claude, "identify_label", fake_identify)
    r = client.post("/api/identify", files={"image": ("e.jpg", b"\xff\xd8", "image/jpeg")})
    assert r.status_code == 200
    assert r.json()["vintage"] == 2017
    bad = client.post("/api/identify", files={"image": ("e.txt", b"hej", "text/plain")})
    assert bad.status_code == 415


def test_frontend_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Vinjæger" in r.text
    assert client.get("/app.js").status_code == 200


# ---- Claude-løkken med en falsk klient ----

class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def fake_client(responses):
    messages = FakeMessages(responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def block(type_, **kw):
    return SimpleNamespace(type=type_, **kw)


@pytest.mark.anyio
async def test_find_offers_handles_pause_turn_then_report(monkeypatch):
    fake, msgs = fake_client([
        SimpleNamespace(stop_reason="pause_turn", content=[block("server_tool_use", name="web_search")]),
        SimpleNamespace(stop_reason="tool_use", content=[
            block("text", text="Færdig"),
            block("tool_use", name="report_offers", id="t1", input=RAW),
        ]),
    ])
    monkeypatch.setattr(claude, "_client", lambda: fake)
    out = await claude.find_offers("Musar", 2019, None)
    assert out == RAW
    assert len(msgs.requests) == 2
    first = msgs.requests[0]
    assert first["model"] == claude.MODEL
    assert first["fallbacks"] == "default"
    assert "2019" in first["messages"][0]["content"]
    # efter pause_turn sendes assistent-svaret med tilbage
    assert msgs.requests[1]["messages"][-1]["role"] == "assistant"


@pytest.mark.anyio
async def test_find_offers_nudges_when_model_forgets_tool(monkeypatch):
    fake, msgs = fake_client([
        SimpleNamespace(stop_reason="end_turn", content=[block("text", text="Her er priserne...")]),
        SimpleNamespace(stop_reason="tool_use", content=[
            block("tool_use", name="report_offers", id="t1", input={"offers": [], "summary": "Intet"}),
        ]),
    ])
    monkeypatch.setattr(claude, "_client", lambda: fake)
    out = await claude.find_offers("Ukendt vin")
    assert out["offers"] == []
    assert msgs.requests[1]["messages"][-1]["role"] == "user"


@pytest.mark.anyio
async def test_find_offers_refusal(monkeypatch):
    fake, _ = fake_client([SimpleNamespace(stop_reason="refusal", content=[])])
    monkeypatch.setattr(claude, "_client", lambda: fake)
    with pytest.raises(claude.ClaudeError):
        await claude.find_offers("x")
