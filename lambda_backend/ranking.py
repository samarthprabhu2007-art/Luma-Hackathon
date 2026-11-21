"""Official NextPay routing and deterministic ranking for AWS Lambda."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any


IST = timezone(timedelta(hours=5, minutes=30))
PROTECTED_FIELDS = {"display_name", "display_area", "language_code"}
PAYMENT_LINK_STATUSES = {"", "ACTIVE", "PARTIALLY_PAID", "PAID", "EXPIRED", "CANCELLED"}

ROUTE_REASONS = {
    "CLOSE_PAID": "Verified receipts cover the current due. Remove from the call queue.",
    "SUPPRESS_OPT_OUT": "The contact asked to stop. Suppress automated calls and messages.",
    "SUPPRESS_WRONG_NUMBER": "The number belongs to a different person. Suppress it for this account.",
    "HUMAN_SUPPORT": "Hardship was reported. Stop automated contact and offer human support.",
    "RECONCILE_CLAIM": "A prior payment was claimed. Pause outreach and check the receipt.",
    "WAIT_PROMISE": "Wait for the promised payment date and check the balance then.",
    "RECHECK_BALANCE": "The promise lapsed. Verify the current balance before reconsidering outreach.",
    "REVIEW_CALLBACK_TIME": "The requested time is outside demo calling hours. Arrange a permitted time.",
    "WAIT_CALLBACK": "Wait until the borrower’s chosen callback time.",
    "WAIT_AGREED_FOLLOWUP": "Wait until the next follow-up agreed after a part payment.",
    "WAIT_WINDOW": "The demo calling window is closed.",
    "COOLDOWN": "An outbound call was attempted in the last 24 hours. Wait until the limit clears.",
}


class RankingInputError(ValueError):
    """Raised when a ranking request has invalid input."""


def _required_id(borrower: dict[str, Any]) -> str:
    if not isinstance(borrower, dict):
        raise RankingInputError("Every borrower must be a JSON object.")
    borrower_id = str(borrower.get("borrower_id", "")).strip()
    if not borrower_id:
        raise RankingInputError("Every borrower must have a non-empty borrower_id.")
    return borrower_id


def _integer(borrower: dict[str, Any], field: str, *, required: bool = True) -> int:
    value = borrower.get(field)
    if value in (None, ""):
        if required:
            raise RankingInputError(f"{field} is required.")
        return 0
    if isinstance(value, bool):
        raise RankingInputError(f"{field} must be a non-negative integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RankingInputError(f"{field} must be a non-negative integer.") from exc
    if parsed < 0 or str(value).strip() not in {str(parsed), f"{parsed}.0"}:
        raise RankingInputError(f"{field} must be a non-negative integer.")
    return parsed


def _flag(borrower: dict[str, Any], field: str) -> bool:
    value = borrower.get(field, 0)
    if value in (0, "0", False, None, ""):
        return False
    if value in (1, "1", True):
        return True
    raise RankingInputError(f"{field} must be 0 or 1.")


def _moment(borrower: dict[str, Any], field: str, *, required: bool = False) -> datetime | None:
    value = borrower.get(field)
    if value in (None, ""):
        if required:
            raise RankingInputError(f"{field} is required.")
        return None
    if not isinstance(value, str):
        raise RankingInputError(f"{field} must be an ISO 8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RankingInputError(f"{field} must be an ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RankingInputError(f"{field} must include a timezone offset.")
    return parsed


def _inside_calling_window(moment: datetime) -> bool:
    hour = moment.astimezone(IST).hour
    return 8 <= hour < 19


def route_borrower(borrower: dict[str, Any]) -> str:
    """Apply the first matching official routing gate in documented order."""
    _required_id(borrower)
    now = _moment(borrower, "as_of_ist", required=True)
    outstanding = _integer(borrower, "outstanding_inr")
    if outstanding == 0:
        return "CLOSE_PAID"

    ordered_flags = (
        ("stop_contact", "SUPPRESS_OPT_OUT"),
        ("wrong_number", "SUPPRESS_WRONG_NUMBER"),
        ("hardship_open", "HUMAN_SUPPORT"),
        ("unverified_payment_claim", "RECONCILE_CLAIM"),
    )
    for field, route in ordered_flags:
        if _flag(borrower, field):
            return route

    promise_due = _moment(borrower, "active_promise_due_ist")
    if promise_due is not None:
        if promise_due > now:
            return "WAIT_PROMISE"
        balance_checked = _moment(borrower, "balance_checked_at_ist")
        if balance_checked is None or balance_checked < promise_due:
            return "RECHECK_BALANCE"

    callback = _moment(borrower, "requested_callback_at_ist")
    if callback is not None:
        if not _inside_calling_window(callback):
            return "REVIEW_CALLBACK_TIME"
        if callback > now:
            return "WAIT_CALLBACK"

    agreed_followup = _moment(borrower, "next_agreed_followup_ist")
    if agreed_followup is not None and agreed_followup > now:
        return "WAIT_AGREED_FOLLOWUP"
    if not _inside_calling_window(now):
        return "WAIT_WINDOW"

    last_attempt = _moment(borrower, "last_outbound_attempt_ist")
    if last_attempt is not None:
        if last_attempt > now:
            raise RankingInputError("last_outbound_attempt_ist cannot be after as_of_ist.")
        if now - last_attempt < timedelta(hours=24):
            return "COOLDOWN"
    return "CALL"


def _score_inputs(borrower: dict[str, Any]) -> tuple[int, int, int]:
    now = _moment(borrower, "as_of_ist", required=True)
    callback = _moment(borrower, "requested_callback_at_ist")
    callback_due = int(callback is not None and callback <= now)
    reminded = _integer(borrower, "prior_payments_after_reminders")
    unaided = _integer(borrower, "prior_unaided_payments")
    return callback_due, reminded, unaided


def score_borrower(borrower: dict[str, Any]) -> int:
    callback_due, reminded, unaided = _score_inputs(borrower)
    return 3 * callback_due + min(2, reminded) - min(2, unaided)


def score_reason(borrower: dict[str, Any]) -> str:
    callback_due, reminded, unaided = _score_inputs(borrower)
    reasons = [
        "Requested callback is due (+3)." if callback_due else "No callback is due (0).",
        f"{reminded} verified past payments followed reminders (+{min(2, reminded)}).",
        f"{unaided} past payments were unaided (-{min(2, unaided)}).",
    ]
    if _moment(borrower, "active_promise_due_ist") is not None:
        reasons.append("The promise date passed and the balance was checked.")
    link_status = str(borrower.get("payment_link_status", "")).strip().upper()
    if link_status not in PAYMENT_LINK_STATUSES:
        raise RankingInputError("payment_link_status is not recognized.")
    if link_status in {"EXPIRED", "CANCELLED"}:
        reasons.append("The old link is no longer active and a balance remains.")
    return " ".join(reasons)


def evaluate_borrower(borrower: dict[str, Any]) -> dict[str, Any]:
    borrower_id = _required_id(borrower)
    route = route_borrower(borrower)
    if route != "CALL":
        return {
            "borrower_id": borrower_id,
            "route": route,
            "eligible": False,
            "score": None,
            "reason": ROUTE_REASONS[route],
        }
    return {
        "borrower_id": borrower_id,
        "route": "CALL",
        "eligible": True,
        "score": score_borrower(borrower),
        "reason": score_reason(borrower),
    }


def rank_borrowers(borrowers: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(borrowers, list):
        raise RankingInputError("borrowers must be a list.")
    evaluated = [evaluate_borrower(item) for item in borrowers]
    ids = [item["borrower_id"] for item in evaluated]
    if len(ids) != len(set(ids)):
        raise RankingInputError("borrower_id values must be unique.")

    ranked = sorted(
        (item for item in evaluated if item["eligible"]),
        key=lambda item: (-item["score"], item["borrower_id"]),
    )
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    excluded = [item for item in evaluated if not item["eligible"]]
    return {
        "ranked": ranked,
        "excluded": excluded,
        "summary": {
            "received": len(evaluated),
            "eligible": len(ranked),
            "excluded": len(excluded),
        },
    }


def swap_test(borrower: dict[str, Any], swap_values: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verify name, language and area cannot alter route, score or reason."""
    _required_id(borrower)
    swap_values = swap_values or {
        "display_name": "Swapped Name",
        "language_code": "kn-IN",
        "display_area": "Swapped Area",
    }
    if not isinstance(swap_values, dict):
        raise RankingInputError("swap_values must be an object.")
    invalid = sorted(set(swap_values) - PROTECTED_FIELDS)
    if invalid:
        raise RankingInputError(
            "swap_values may only contain: " + ", ".join(sorted(PROTECTED_FIELDS))
        )
    original_result = evaluate_borrower(borrower)
    swapped_result = evaluate_borrower({**borrower, **swap_values})
    return {
        "passed": original_result == swapped_result,
        "fields_swapped": sorted(swap_values),
        "original": original_result,
        "swapped": swapped_result,
    }


def process_request(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RankingInputError("Request payload must be a JSON object.")
    action = payload.get("action", "rank")
    if action == "rank":
        return rank_borrowers(payload.get("borrowers"))
    if action == "swap_test":
        return swap_test(payload.get("borrower"), payload.get("swap_values"))
    raise RankingInputError("action must be 'rank' or 'swap_test'.")


def _payload_from_event(event: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if not isinstance(event, dict):
        raise RankingInputError("Lambda event must be a JSON object.")
    is_http = "requestContext" in event or "body" in event
    if not is_http:
        return event, False
    body = event.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RankingInputError("Request body must contain valid JSON.") from exc
    if not isinstance(body, dict):
        raise RankingInputError("Request body must be a JSON object.")
    return body, True


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle direct Lambda invocations and HTTP proxy invocations."""
    is_http = isinstance(event, dict) and ("requestContext" in event or "body" in event)
    try:
        payload, is_http = _payload_from_event(event)
        result = process_request(payload)
        if not is_http:
            return result
        return {
            "statusCode": 200,
            "headers": {"content-type": "application/json"},
            "body": json.dumps(result),
        }
    except RankingInputError as exc:
        error = {"error": str(exc)}
        if not is_http:
            return error
        return {
            "statusCode": 400,
            "headers": {"content-type": "application/json"},
            "body": json.dumps(error),
        }
