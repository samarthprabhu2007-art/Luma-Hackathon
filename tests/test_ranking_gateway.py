import json

import ranking_gateway
import pytest


@pytest.fixture(autouse=True)
def ranking_mode(monkeypatch):
    monkeypatch.setenv("RANKING_MODE", "lambda")


def borrower(borrower_id="B001"):
    return {
        "borrower_id": borrower_id,
        "as_of_ist": "2026-11-21T14:30:00+05:30",
        "outstanding_inr": 1000,
        "prior_payments_after_reminders": 1,
        "prior_unaided_payments": 0,
        "requested_callback_at_ist": "",
        "active_promise_due_ist": "",
        "next_agreed_followup_ist": "",
        "balance_checked_at_ist": "2026-11-19T14:30:00+05:30",
        "last_outbound_attempt_ist": "",
        "unverified_payment_claim": 0,
        "hardship_open": 0,
        "wrong_number": 0,
        "stop_contact": 0,
        "payment_link_status": "ACTIVE",
    }


def result():
    return {
        "ranked": [{
            "borrower_id": "B001",
            "route": "CALL",
            "eligible": True,
            "score": 1,
            "reason": (
                "No callback is due (0). 1 verified past payments followed reminders (+1). "
                "0 past payments were unaided (-0)."
            ),
            "rank": 1,
        }],
        "excluded": [],
        "summary": {"received": 1, "eligible": 1, "excluded": 0},
    }


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_unconfigured_gateway_uses_existing_local_engine(monkeypatch):
    monkeypatch.setenv("RANKING_MODE", "local")
    monkeypatch.delenv("RANKING_LAMBDA_URL", raising=False)
    ranked = ranking_gateway.rank_borrowers([borrower()])
    assert ranked["ranking_source"] == "local"
    assert ranked["ranked"][0]["borrower_id"] == "B001"
    assert ranked["ranked"][0]["score"] == 1


def test_configured_gateway_sends_actual_direct_handler_event(monkeypatch):
    monkeypatch.setenv("RANKING_LAMBDA_URL", "https://example.test/stuthir26-ranking/")
    captured = {}

    def fake_post(url, *, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return FakeResponse(result())

    monkeypatch.setattr(ranking_gateway.httpx, "post", fake_post)
    ranked = ranking_gateway.rank_borrowers([borrower()])
    assert captured == {
        "url": "https://example.test/stuthir26-ranking/",
        "json": {"action": "rank", "borrowers": [borrower()]},
        "timeout": 10.0,
    }
    assert ranked["ranking_source"] == "lambda"
    assert ranked["summary"] == {"received": 1, "eligible": 1, "excluded": 0}


def test_gateway_unwraps_actual_http_handler_response(monkeypatch):
    monkeypatch.setenv("RANKING_LAMBDA_URL", "https://example.test/stuthir26-ranking/")
    envelope = {
        "statusCode": 200,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(result()),
    }
    monkeypatch.setattr(
        ranking_gateway.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(envelope),
    )
    ranked = ranking_gateway.rank_borrowers([borrower()])
    assert ranked["ranking_source"] == "lambda"
    assert ranked["ranked"][0]["route"] == "CALL"


def test_gateway_rejects_lambda_error_envelope(monkeypatch):
    monkeypatch.setenv("RANKING_LAMBDA_URL", "https://example.test/stuthir26-ranking/")
    envelope = {"statusCode": 400, "body": json.dumps({"error": "bad request"})}
    monkeypatch.setattr(
        ranking_gateway.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(envelope),
    )
    try:
        ranking_gateway.rank_borrowers([borrower()])
    except ranking_gateway.RankingGatewayError as exc:
        assert "bad request" in str(exc)
    else:
        raise AssertionError("Expected RankingGatewayError")
