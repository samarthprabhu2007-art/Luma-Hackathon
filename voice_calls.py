"""Outbound voice calls through Sarvam Voice Agents (Samvaad) "instant outbound".

Safeguards, because these ring real phones and the server may be reachable through a tunnel:
- only numbers listed in data/call_contacts.csv can be called, never an arbitrary number;
- calls are refused outside 8 AM to 7 PM IST;
- borrowers flagged stop_contact, wrong_number or hardship_open are never called;
- dry_run returns exactly what would be sent without placing a call.
"""
import csv
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/calls")

IST = timezone(timedelta(hours=5, minutes=30))
CONTACTS_FILE = Path(__file__).with_name("data") / "call_contacts.csv"
BASE = "https://apps.sarvam.ai/api/outbounds/v1"
LANGUAGE_NAME = {"kn-IN": "Kannada", "hi-IN": "Hindi", "ta-IN": "Tamil", "te-IN": "Telugu", "en-IN": "English"}
REQUIRED = ["SARVAM_VOICE_API_KEY", "SARVAM_VOICE_ORG_ID", "SARVAM_VOICE_WORKSPACE_ID", "SARVAM_VOICE_APP_ID",
            "SARVAM_VOICE_APP_VERSION", "SARVAM_VOICE_CONNECTION_ID", "SARVAM_VOICE_AGENT_PHONE"]
CALLS: list[dict] = []  # calls requested since the server started (in memory)


def now_ist() -> datetime:
    return datetime.now(IST)


def window_open(moment: datetime | None = None) -> bool:
    return 8 <= (moment or now_ist()).hour < 19


def missing_settings() -> list[str]:
    return [name for name in REQUIRED if not os.getenv(name, "").strip()]


def e164(phone: str) -> str:
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    return "+" + digits if len(digits) > 10 else "+91" + digits


def contacts() -> list[dict]:
    if not CONTACTS_FILE.is_file():
        return []
    rows = []
    with open(CONTACTS_FILE, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if not (row.get("borrower_id") or "").strip() or not (row.get("phone") or "").strip():
                continue
            rows.append({
                "borrower_id": row["borrower_id"].strip(), "name": (row.get("display_name") or "").strip(),
                "phone": e164(row["phone"]), "language_code": (row.get("language_code") or "en-IN").strip(),
                "outstanding_inr": int(float(row.get("outstanding_inr") or 0)),
                "blocked": any(str(row.get(f) or "0").strip() == "1" for f in ("stop_contact", "wrong_number", "hardship_open")),
            })
    return rows


def mask(phone: str) -> str:
    return "+91 ••••• ••" + phone[-3:]


def build_payload(contact: dict) -> dict:
    lang = LANGUAGE_NAME.get(contact["language_code"], "English")
    return {
        "app_config": {
            "app_id": os.environ["SARVAM_VOICE_APP_ID"],
            "app_version": int(os.environ["SARVAM_VOICE_APP_VERSION"]),
            "connection_config": {"connection_id": os.environ["SARVAM_VOICE_CONNECTION_ID"],
                                  "agent_phone_number": e164(os.environ["SARVAM_VOICE_AGENT_PHONE"])},
            "agent_variables": {"customer_name": contact["name"], "amount": str(contact["outstanding_inr"]),
                                "lender_name": os.getenv("LENDER_NAME", "Demo Finance")},
            "app_overrides": {"initial_language_name": lang},
        },
        "user_config": {"user_phone_number": contact["phone"]},
    }


class CallRequest(BaseModel):
    borrower_id: str
    dry_run: bool = False


@router.get("/contacts")
def list_contacts():
    return {"contacts": [{**c, "phone_masked": mask(c["phone"]), "phone": None} for c in contacts()],
            "missing_settings": missing_settings(), "window_open": window_open(), "now_ist": now_ist().strftime("%H:%M")}


@router.get("/log")
def call_log():
    return list(reversed(CALLS[-100:]))


@router.post("")
def place_call(req: CallRequest):
    contact = next((c for c in contacts() if c["borrower_id"] == req.borrower_id), None)
    if contact is None:
        raise HTTPException(404, "That borrower is not on the approved call list.")
    if contact["blocked"]:
        raise HTTPException(409, "This borrower asked not to be contacted, has the wrong number, or has an open hardship case.")
    if not window_open():
        raise HTTPException(409, "Calls are only allowed between 8 AM and 7 PM IST.")
    missing = missing_settings()
    if missing:
        raise HTTPException(503, "Sarvam Voice settings missing in .env: " + ", ".join(missing))

    payload = build_payload(contact)
    if req.dry_run:
        return {"dry_run": True, "would_call": mask(contact["phone"]), "payload": payload}

    url = f"{BASE}/orgs/{os.environ['SARVAM_VOICE_ORG_ID']}/workspaces/{os.environ['SARVAM_VOICE_WORKSPACE_ID']}/outbounds"
    try:
        res = httpx.post(url, json=payload, headers={"X-API-Key": os.environ["SARVAM_VOICE_API_KEY"],
                                                     "Content-Type": "application/json"}, timeout=30)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach Sarvam Voice: {exc}") from exc
    if res.status_code >= 400:
        raise HTTPException(502, f"Sarvam Voice refused the call ({res.status_code}): {res.text[:400]}")
    attempt = res.json().get("attempt_id")
    CALLS.append({"borrower_id": contact["borrower_id"], "name": contact["name"], "attempt_id": attempt,
                  "language": LANGUAGE_NAME.get(contact["language_code"], "English"),
                  "requested_at": now_ist().isoformat(timespec="seconds"), "phone_masked": mask(contact["phone"])})
    return {"attempt_id": attempt, "calling": mask(contact["phone"])}
