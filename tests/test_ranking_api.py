from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as appmod


client = TestClient(appmod.app)


def test_rank_action_reuses_gateway(monkeypatch):
    expected = {
        "ranked": [],
        "excluded": [],
        "summary": {"received": 0, "eligible": 0, "excluded": 0},
        "ranking_source": "lambda",
    }
    monkeypatch.setattr(appmod.ranking_gateway, "rank_borrowers", lambda borrowers: expected)
    assert appmod.rank(appmod.RankingRequest(borrowers=[])) == expected


def test_rank_action_maps_remote_failure_to_502(monkeypatch):
    def fail(_borrowers):
        raise appmod.ranking_gateway.RankingGatewayError("offline")

    monkeypatch.setattr(appmod.ranking_gateway, "rank_borrowers", fail)
    try:
        appmod.rank(appmod.RankingRequest(borrowers=[]))
    except HTTPException as exc:
        assert exc.status_code == 502
        assert exc.detail == "offline"
    else:
        raise AssertionError("Expected HTTPException")


def test_http_rank_route_delegates_to_lambda_gateway(monkeypatch):
    expected = {
        "ranked": [{
            "borrower_id": "B001",
            "route": "CALL",
            "eligible": True,
            "score": 1,
            "reason": "auditable reason",
            "rank": 1,
        }],
        "excluded": [],
        "summary": {"received": 1, "eligible": 1, "excluded": 0},
        "ranking_source": "lambda",
    }
    captured = {}

    def fake_rank(borrowers):
        captured["borrowers"] = borrowers
        return expected

    monkeypatch.setattr(appmod.ranking_gateway, "rank_borrowers", fake_rank)
    borrower = {"borrower_id": "B001"}
    response = client.post("/api/rank", json={"borrowers": [borrower]})
    assert response.status_code == 200
    assert response.json() == expected
    assert captured["borrowers"] == [borrower]
