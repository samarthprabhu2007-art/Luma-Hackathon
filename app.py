"""Level 1: Sarvam reminder + Cashfree payment link + PAID status.

Run:  uvicorn app:app --reload --port 8000
"""
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv(Path(__file__).with_name(".env"))

import cashfree  # noqa: E402
from sarvam_client import create_sarvam_client  # noqa: E402
from sarvam_reminder import generate_reminder  # noqa: E402

LANGS = {"hi": "hi-IN", "kn": "kn-IN", "ta": "ta-IN", "te": "te-IN"}  # what sarvam_reminder supports

app = FastAPI(title="Level 1 reminder + pay")
EVENTS: list[dict] = []  # webhook log (in memory)


class Reminder(BaseModel):
    name: str
    phone: str
    amount: float
    language: str = "hi"


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"cashfree_configured": cashfree.configured(),
            "sarvam_configured": create_sarvam_client() is not None,
            "webhook_public_url": bool(os.getenv("PUBLIC_BASE_URL"))}


@app.post("/api/remind")
def remind(req: Reminder):
    if req.language not in LANGS:
        raise HTTPException(400, f"language must be one of {list(LANGS)}")
    if not re.fullmatch(r"\d{10}", req.phone):
        raise HTTPException(400, "phone must be 10 digits")
    if req.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    if not cashfree.configured():
        raise HTTPException(503, "Cashfree keys missing in .env")

    lender = os.getenv("LENDER_NAME", "Demo Finance")
    notes = []  # shown in the UI so failures are visible, never silent

    # 1. language: Sarvam translate + TTS; the module falls back to a template itself
    client = create_sarvam_client()
    try:
        rem = generate_reminder(name=req.name, lender=lender, amount=f"{req.amount:g}",
                                language=LANGS[req.language], client=client)
        text, audio, used_template = rem.text, rem.audio_base64, rem.used_template
    except Exception as e:  # noqa: BLE001  Sarvam must never block the payment
        text, audio, used_template = f"Payment reminder for {req.name}: Rs {req.amount:g} due.", None, True
        notes.append(f"Sarvam step crashed, plain English used: {e}")
    if client is None:
        notes.append("SARVAM_API_KEY not set, used template")
    elif used_template:
        notes.append("Sarvam translation unavailable, used template")
    if client is not None and audio is None:
        notes.append("Sarvam audio unavailable, text only")

    # 2. money: this must work
    try:
        link = cashfree.create_link(req.name, req.phone, req.amount)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e))

    return {"text": text, "text_source": "template" if used_template else "sarvam",
            "audio_b64": audio, "notes": notes, "amount": req.amount,
            "link_id": link["link_id"], "link_url": link["link_url"], "link_status": link["link_status"]}


@app.get("/api/status/{link_id}")
def status(link_id: str):
    try:
        link = cashfree.get_link(link_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e))
    return {"link_id": link_id, "link_status": link.get("link_status"),
            "amount_paid": link.get("link_amount_paid")}


@app.post("/webhook")
async def webhook(request: Request):
    raw = await request.body()
    ok = cashfree.verify_webhook(raw, request.headers.get("x-webhook-timestamp", ""),
                                 request.headers.get("x-webhook-signature", ""))
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {"raw": raw.decode(errors="replace")}
    EVENTS.append({"verified": ok, "payload": payload})
    return {"ok": True}


@app.get("/api/events")
def events():
    return EVENTS[-20:]
