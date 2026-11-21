"""Offline tests: external APIs are faked, so these prove OUR logic and the fallback ladder.
They do not prove the live Cashfree/Sarvam calls; run the live smoke test for that."""
import base64
import hashlib
import hmac
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["CASHFREE_CLIENT_ID"] = "id"
os.environ["CASHFREE_CLIENT_SECRET"] = "secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as appmod  # noqa: E402
import cashfree  # noqa: E402
from sarvam_reminder import Reminder  # noqa: E402

client = TestClient(appmod.app)
BODY = {"name": "Lakshmi", "phone": "9999999999", "amount": 500, "language": "kn"}


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(cashfree, "create_link", lambda *a, **k: {
        "link_id": "L1_x", "link_url": "https://payments-test.cashfree.com/links/x", "link_status": "ACTIVE"})
    monkeypatch.setattr(cashfree, "get_link", lambda i: {"link_status": "PAID", "link_amount_paid": 500})
    monkeypatch.setattr(appmod, "create_sarvam_client", lambda: object())


def test_sarvam_ok(monkeypatch):
    monkeypatch.setattr(appmod, "generate_reminder", lambda **k: Reminder("ಅನುವಾದ", "QUJD", False))
    d = client.post("/api/remind", json=BODY).json()
    assert d["text_source"] == "sarvam" and d["audio_b64"] == "QUJD" and d["link_status"] == "ACTIVE"
    assert d["notes"] == []


def test_sarvam_template_and_no_audio_still_pays(monkeypatch):
    monkeypatch.setattr(appmod, "generate_reminder", lambda **k: Reminder("template", None, True))
    d = client.post("/api/remind", json=BODY).json()
    assert d["text_source"] == "template" and d["audio_b64"] is None and d["link_url"]
    assert len(d["notes"]) == 2  # failures are visible, not silent


def test_sarvam_crash_still_pays(monkeypatch):
    def boom(**k): raise RuntimeError("down")
    monkeypatch.setattr(appmod, "generate_reminder", boom)
    r = client.post("/api/remind", json=BODY)
    assert r.status_code == 200 and r.json()["link_url"] and "crashed" in r.json()["notes"][0]


def test_no_sarvam_key_still_pays(monkeypatch):
    monkeypatch.setattr(appmod, "create_sarvam_client", lambda: None)
    d = client.post("/api/remind", json=BODY).json()
    assert d["text_source"] == "template" and d["link_url"]
    assert "SARVAM_API_KEY not set, used template" in d["notes"]


def test_cashfree_failure_is_loud(monkeypatch):
    def boom(*a, **k): raise RuntimeError("cashfree 401")
    monkeypatch.setattr(cashfree, "create_link", boom)
    monkeypatch.setattr(appmod, "generate_reminder", lambda **k: Reminder("t", None, True))
    assert client.post("/api/remind", json=BODY).status_code == 502


def test_links_registry_records_each_pay_link(monkeypatch):
    monkeypatch.setattr(appmod, "generate_reminder", lambda **k: Reminder("t", None, True))
    appmod.LINKS.clear()
    client.post("/api/remind", json={**BODY, "borrower_id": "LN-1"})
    listed = client.get("/api/links").json()
    assert len(listed) == 1
    assert listed[0]["borrower_id"] == "LN-1" and listed[0]["link_id"] == "L1_x" and listed[0]["amount"] == 500


def test_sms_delivery_is_opt_in_and_passes_text_to_cashfree(monkeypatch):
    seen = {}
    def fake_create(name, phone, amount, **kw):
        seen.update(kw)
        return {"link_id": "L1_x", "link_url": "https://payments-test.cashfree.com/links/x", "link_status": "ACTIVE"}
    monkeypatch.setattr(cashfree, "create_link", fake_create)
    monkeypatch.setattr(appmod, "generate_reminder", lambda **k: Reminder("ನಮಸ್ಕಾರ", None, False))
    monkeypatch.setattr(appmod, "LINKS", [])
    client.post("/api/remind", json=BODY)
    assert seen["notify_sms"] is False and seen["purpose"] == "ನಮಸ್ಕಾರ"  # message shown on the pay page
    d = client.post("/api/remind", json={**BODY, "phone": "9876543210", "deliver_sms": True}).json()
    assert seen["notify_sms"] is True and d["sms_requested"] is True and d["phone_tail"] == "3210"


def test_sms_to_the_demo_placeholder_number_is_refused():
    r = client.post("/api/remind", json={**BODY, "deliver_sms": True})  # BODY uses 9999999999
    assert r.status_code == 400 and "real phone" in r.json()["detail"]


def test_validation():
    assert client.post("/api/remind", json={**BODY, "phone": "123"}).status_code == 400
    assert client.post("/api/remind", json={**BODY, "amount": 0}).status_code == 400
    assert client.post("/api/remind", json={**BODY, "language": "xx"}).status_code == 400


def test_status_and_webhook_signature():
    assert client.get("/api/status/L1_x").json()["link_status"] == "PAID"
    raw, ts = b'{"type":"PAYMENT_LINK_EVENT"}', "1700000000"
    sig = base64.b64encode(hmac.new(b"secret", ts.encode() + raw, hashlib.sha256).digest()).decode()
    client.post("/webhook", content=raw, headers={"x-webhook-timestamp": ts, "x-webhook-signature": sig})
    client.post("/webhook", content=raw, headers={"x-webhook-timestamp": ts, "x-webhook-signature": "bad"})
    ev = client.get("/api/events").json()
    assert ev[-2]["verified"] is True and ev[-1]["verified"] is False
