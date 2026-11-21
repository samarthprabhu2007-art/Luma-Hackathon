"""Cashfree sandbox Payment Links. The only hard dependency of Level 1."""
import base64
import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx

IST = timezone(timedelta(hours=5, minutes=30))


def configured() -> bool:
    return bool(os.getenv("CASHFREE_CLIENT_ID") and os.getenv("CASHFREE_CLIENT_SECRET"))


def _headers() -> dict:
    return {
        "x-client-id": os.environ["CASHFREE_CLIENT_ID"],
        "x-client-secret": os.environ["CASHFREE_CLIENT_SECRET"],
        "x-api-version": os.getenv("CASHFREE_API_VERSION", "2023-08-01"),
        "Content-Type": "application/json",
    }


def _base() -> str:
    return os.getenv("CASHFREE_BASE", "https://sandbox.cashfree.com/pg").rstrip("/")


def create_link(name: str, phone: str, amount: float, purpose: str = "Payment reminder",
                partial: bool = True, min_partial: float | None = None) -> dict:
    """Create a payment link. Returns Cashfree's JSON (has link_id, link_url, link_status)."""
    body = {
        "link_id": "L1_" + uuid.uuid4().hex[:16],
        "link_amount": float(amount),
        "link_currency": "INR",
        "link_purpose": purpose,
        "customer_details": {"customer_name": name, "customer_phone": phone},
        "link_partial_payments": partial,
        "link_expiry_time": (datetime.now(IST) + timedelta(days=1)).isoformat(timespec="seconds"),
        "link_notify": {"send_sms": False, "send_email": False},
    }
    if partial:
        body["link_minimum_partial_amount"] = float(min_partial or max(1, round(float(amount) * 0.2)))
    public = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if public:
        body["link_meta"] = {"notify_url": public + "/webhook"}
    r = httpx.post(_base() + "/links", json=body, headers=_headers(), timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"Cashfree create link failed {r.status_code}: {r.text}")
    return r.json()


def get_link(link_id: str) -> dict:
    r = httpx.get(f"{_base()}/links/{link_id}", headers=_headers(), timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"Cashfree get link failed {r.status_code}: {r.text}")
    return r.json()


def verify_webhook(raw_body: bytes, timestamp: str, signature: str) -> bool:
    """Cashfree signs timestamp + raw body with the client secret (HMAC-SHA256, base64)."""
    secret = os.getenv("CASHFREE_CLIENT_SECRET", "")
    if not (secret and timestamp and signature):
        return False
    digest = hmac.new(secret.encode(), timestamp.encode() + raw_body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)
