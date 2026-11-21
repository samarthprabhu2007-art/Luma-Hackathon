import csv
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from lambda_backend.ranking import (
    RankingInputError,
    evaluate_borrower,
    lambda_handler,
    rank_borrowers,
    route_borrower,
    swap_test,
)


IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 21, 14, 30, tzinfo=IST)


def stamp(moment):
    return moment.isoformat(timespec="seconds") if moment else ""


def borrower(borrower_id="B001", **changes):
    record = {
        "borrower_id": borrower_id,
        "as_of_ist": stamp(NOW),
        "outstanding_inr": 1000,
        "prior_payments_after_reminders": 0,
        "prior_unaided_payments": 0,
        "requested_callback_at_ist": "",
        "active_promise_due_ist": "",
        "next_agreed_followup_ist": "",
        "balance_checked_at_ist": stamp(NOW - timedelta(days=2)),
        "last_outbound_attempt_ist": "",
        "unverified_payment_claim": 0,
        "hardship_open": 0,
        "wrong_number": 0,
        "stop_contact": 0,
        "payment_link_status": "ACTIVE",
    }
    record.update(changes)
    return record


@pytest.mark.parametrize(
    ("changes", "route"),
    [
        ({"outstanding_inr": 0, "stop_contact": 1}, "CLOSE_PAID"),
        ({"stop_contact": 1, "wrong_number": 1}, "SUPPRESS_OPT_OUT"),
        ({"wrong_number": 1, "hardship_open": 1}, "SUPPRESS_WRONG_NUMBER"),
        ({"hardship_open": 1, "unverified_payment_claim": 1}, "HUMAN_SUPPORT"),
        ({"unverified_payment_claim": 1}, "RECONCILE_CLAIM"),
        ({"active_promise_due_ist": stamp(NOW + timedelta(days=1))}, "WAIT_PROMISE"),
        ({"active_promise_due_ist": stamp(NOW - timedelta(days=1))}, "RECHECK_BALANCE"),
        ({"requested_callback_at_ist": stamp(NOW.replace(hour=19))}, "REVIEW_CALLBACK_TIME"),
        ({"requested_callback_at_ist": stamp(NOW + timedelta(hours=1))}, "WAIT_CALLBACK"),
        ({"next_agreed_followup_ist": stamp(NOW + timedelta(days=1))}, "WAIT_AGREED_FOLLOWUP"),
        ({"as_of_ist": stamp(NOW.replace(hour=19))}, "WAIT_WINDOW"),
        ({"last_outbound_attempt_ist": stamp(NOW - timedelta(hours=23, minutes=59))}, "COOLDOWN"),
    ],
)
def test_ordered_routes(changes, route):
    assert route_borrower(borrower(**changes)) == route


def test_window_and_cooldown_boundaries_are_inclusive_as_documented():
    assert route_borrower(borrower(as_of_ist=stamp(NOW.replace(hour=8, minute=0)))) == "CALL"
    assert route_borrower(borrower(as_of_ist=stamp(NOW.replace(hour=7, minute=59)))) == "WAIT_WINDOW"
    assert route_borrower(borrower(as_of_ist=stamp(NOW.replace(hour=18, minute=59)))) == "CALL"
    assert route_borrower(borrower(as_of_ist=stamp(NOW.replace(hour=19, minute=0)))) == "WAIT_WINDOW"
    assert route_borrower(borrower(last_outbound_attempt_ist=stamp(NOW - timedelta(hours=24)))) == "CALL"


def test_ranking_formula_and_stable_tie_break():
    result = rank_borrowers([
        borrower("B003", prior_payments_after_reminders=1),
        borrower("B001", requested_callback_at_ist=stamp(NOW)),
        borrower("B002", prior_payments_after_reminders=1),
        borrower("B004", prior_unaided_payments=5),
    ])
    assert [(row["borrower_id"], row["score"], row["rank"]) for row in result["ranked"]] == [
        ("B001", 3, 1), ("B002", 1, 2), ("B003", 1, 3), ("B004", -2, 4)
    ]


def test_reason_includes_capped_weights_and_operational_context():
    result = evaluate_borrower(borrower(
        requested_callback_at_ist=stamp(NOW),
        prior_payments_after_reminders=6,
        prior_unaided_payments=4,
        active_promise_due_ist=stamp(NOW - timedelta(days=1)),
        balance_checked_at_ist=stamp(NOW),
        payment_link_status="EXPIRED",
    ))
    assert result["score"] == 3
    assert result["reason"] == (
        "Requested callback is due (+3). 6 verified past payments followed reminders (+2). "
        "4 past payments were unaided (-2). The promise date passed and the balance was checked. "
        "The old link is no longer active and a balance remains."
    )


def test_swap_test_is_invariant():
    original = borrower(display_name="Asha", language_code="hi-IN", display_area="North")
    result = swap_test(original, {
        "display_name": "Kavya", "language_code": "kn-IN", "display_area": "South"
    })
    assert result["passed"] is True
    assert result["original"] == result["swapped"]


@pytest.mark.parametrize(
    "changes",
    [
        {"as_of_ist": "not-a-date"},
        {"as_of_ist": "2026-11-21T14:30:00"},
        {"outstanding_inr": -1},
        {"stop_contact": 2},
        {"prior_unaided_payments": 1.5},
        {"last_outbound_attempt_ist": stamp(NOW + timedelta(seconds=1))},
    ],
)
def test_malformed_or_impossible_inputs_are_rejected(changes):
    with pytest.raises(RankingInputError):
        evaluate_borrower(borrower(**changes))


def test_duplicate_ids_are_rejected():
    with pytest.raises(RankingInputError, match="unique"):
        rank_borrowers([borrower(), borrower()])


def test_http_contract_and_bad_json():
    event = {"requestContext": {}, "body": json.dumps({"borrowers": [borrower()]})}
    response = lambda_handler(event, None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["ranked"][0]["route"] == "CALL"
    assert lambda_handler({"requestContext": {}, "body": "not-json"}, None)["statusCode"] == 400


def test_all_6000_training_labels_routes_scores_reasons_and_ranks():
    with zipfile.ZipFile("NextPay_Training_v1.zip") as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read("borrowers.csv").decode("utf-8-sig"))))

    result = rank_borrowers(rows)
    actual = {item["borrower_id"]: item for item in result["ranked"] + result["excluded"]}
    assert len(actual) == 6000
    for row in rows:
        item = actual[row["borrower_id"]]
        assert item["route"] == row["expected_route"]
        assert item["reason"] == row["score_reason"]
        if row["expected_route"] == "CALL":
            assert item["score"] == int(row["priority_score"])
            assert item["rank"] == int(row["expected_rank"])
        else:
            assert item["score"] is None
