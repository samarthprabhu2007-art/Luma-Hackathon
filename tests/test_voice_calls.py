"""Outbound voice calls. Sarvam is faked, so nothing here can ring a real phone."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import voice_calls  # noqa: E402

CSV = """borrower_id,loan_number,display_name,phone,display_area,language_code,outstanding_inr,stop_contact,wrong_number,hardship_open
B-1,L1,Asha,9000000001,Area,kn-IN,500,0,0,0
B-2,L2,Ravi,9000000002,Area,en-IN,750,1,0,0
B-3,L3,Meena,9000000003,Area,hi-IN,1000,0,0,1
"""
SETTINGS = {"SARVAM_VOICE_API_KEY": "k", "SARVAM_VOICE_ORG_ID": "org1", "SARVAM_VOICE_WORKSPACE_ID": "ws1",
            "SARVAM_VOICE_APP_ID": "app1", "SARVAM_VOICE_APP_VERSION": "2", "SARVAM_VOICE_CONNECTION_ID": "conn1",
            "SARVAM_VOICE_AGENT_PHONE": "+918000000000"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    f = tmp_path / "contacts.csv"
    f.write_text(CSV, encoding="utf-8")
    monkeypatch.setattr(voice_calls, "CONTACTS_FILE", f)
    monkeypatch.setattr(voice_calls, "CALLS", [])
    for k, v in SETTINGS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(voice_calls, "now_ist", lambda: datetime(2026, 11, 21, 15, 0, tzinfo=voice_calls.IST))
    app = FastAPI()
    app.include_router(voice_calls.router)
    return TestClient(app)


class FakeResponse:
    status_code = 200
    text = ""
    def json(self): return {"attempt_id": "att-123456789"}


def test_places_a_call_with_sarvams_documented_request(api, monkeypatch):
    sent = {}
    def fake_post(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers)
        return FakeResponse()
    monkeypatch.setattr(voice_calls.httpx, "post", fake_post)
    d = api.post("/api/calls", json={"borrower_id": "B-1"}).json()
    assert d["attempt_id"] == "att-123456789" and "001" in d["calling"]
    assert sent["url"] == "https://apps.sarvam.ai/api/outbounds/v1/orgs/org1/workspaces/ws1/outbounds"
    assert sent["headers"]["X-API-Key"] == "k"
    cfg = sent["json"]["app_config"]
    assert cfg["app_id"] == "app1" and cfg["app_version"] == 2
    assert cfg["connection_config"] == {"connection_id": "conn1", "agent_phone_number": "+918000000000"}
    assert cfg["agent_variables"]["customer_name"] == "Asha" and cfg["agent_variables"]["amount"] == "500"
    assert cfg["app_overrides"]["initial_language_name"] == "Kannada"
    assert sent["json"]["user_config"] == {"user_phone_number": "+919000000001"}


def test_dry_run_places_nothing(api, monkeypatch):
    monkeypatch.setattr(voice_calls.httpx, "post", lambda *a, **k: pytest.fail("a call was placed"))
    d = api.post("/api/calls", json={"borrower_id": "B-1", "dry_run": True}).json()
    assert d["dry_run"] is True and d["payload"]["user_config"]["user_phone_number"] == "+919000000001"
    assert "X-API-Key" not in str(d) and "k" != d.get("key")


def test_only_the_approved_list_can_be_called(api, monkeypatch):
    monkeypatch.setattr(voice_calls.httpx, "post", lambda *a, **k: pytest.fail("a call was placed"))
    assert api.post("/api/calls", json={"borrower_id": "B-UNKNOWN"}).status_code == 404


def test_stop_contact_and_hardship_are_never_called(api, monkeypatch):
    monkeypatch.setattr(voice_calls.httpx, "post", lambda *a, **k: pytest.fail("a call was placed"))
    assert api.post("/api/calls", json={"borrower_id": "B-2"}).status_code == 409
    assert api.post("/api/calls", json={"borrower_id": "B-3"}).status_code == 409


def test_refuses_outside_the_calling_window(api, monkeypatch):
    monkeypatch.setattr(voice_calls.httpx, "post", lambda *a, **k: pytest.fail("a call was placed"))
    monkeypatch.setattr(voice_calls, "now_ist", lambda: datetime(2026, 11, 21, 19, 30, tzinfo=voice_calls.IST))
    r = api.post("/api/calls", json={"borrower_id": "B-1"})
    assert r.status_code == 409 and "8 AM and 7 PM" in r.json()["detail"]
    monkeypatch.setattr(voice_calls, "now_ist", lambda: datetime(2026, 11, 21, 7, 59, tzinfo=voice_calls.IST))
    assert api.post("/api/calls", json={"borrower_id": "B-1"}).status_code == 409


def test_missing_settings_are_named(api, monkeypatch):
    monkeypatch.delenv("SARVAM_VOICE_ORG_ID")
    r = api.post("/api/calls", json={"borrower_id": "B-1"})
    assert r.status_code == 503 and "SARVAM_VOICE_ORG_ID" in r.json()["detail"]


def test_sarvam_errors_are_loud_and_not_logged_as_calls(api, monkeypatch):
    class Bad(FakeResponse):
        status_code = 422
        text = "bad connection"
    monkeypatch.setattr(voice_calls.httpx, "post", lambda *a, **k: Bad())
    r = api.post("/api/calls", json={"borrower_id": "B-1"})
    assert r.status_code == 502 and "422" in r.json()["detail"]
    assert api.get("/api/calls/log").json() == []


def test_contacts_never_expose_full_numbers(api):
    d = api.get("/api/calls/contacts").json()
    assert "9000000001" not in str(d) and d["window_open"] is True and d["missing_settings"] == []
    assert [c["blocked"] for c in d["contacts"]] == [False, True, True]
