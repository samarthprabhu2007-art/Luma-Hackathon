"""Level 1: Sarvam reminder + Cashfree payment link + PAID status.

Run:  uvicorn app:app --reload --port 8000
"""
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from lender_ocr import router as lender_ocr_router
from pydantic import BaseModel

load_dotenv(Path(__file__).with_name(".env"))

import cashfree  # noqa: E402
import ranking_gateway  # noqa: E402
from lambda_backend.ranking import RankingInputError  # noqa: E402
from sarvam_client import create_sarvam_client  # noqa: E402
from sarvam_reminder import generate_reminder  # noqa: E402

LANGS = {"hi": "hi-IN", "kn": "kn-IN", "ta": "ta-IN", "te": "te-IN"}  # what sarvam_reminder supports
PLACEHOLDER_PHONE = "9999999999"  # the demo default; never text it

app = FastAPI(title="Level 1 reminder + pay")
from shared_book import router as book_router
app.include_router(book_router)
from collections_actions import router as collections_router
app.include_router(collections_router)
app.include_router(lender_ocr_router)
from voice_calls import router as voice_calls_router
app.include_router(voice_calls_router)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
EVENTS: list[dict] = []  # webhook log (in memory)
LINKS: list[dict] = []  # pay links created since the server started (in memory)


class Reminder(BaseModel):
    name: str
    phone: str
    amount: float
    language: str = "hi"
    include_audio: bool = True  # Relay HTTP steps can set false to keep the response small
    borrower_id: str | None = None  # loan id from the dashboard, kept for the Payments page
    deliver_sms: bool = False  # ask Cashfree to text the pay link to the borrower's phone


class RankingRequest(BaseModel):
    borrowers: list[dict]


@app.get("/")
def dashboard():
    return FileResponse(Path(__file__).parent / "static" / "lender.html")


@app.get("/reminder")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"cashfree_configured": cashfree.configured(),
            "sarvam_configured": create_sarvam_client() is not None,
            "ranking_lambda_configured": ranking_gateway.configured(),
            "webhook_public_url": bool(os.getenv("PUBLIC_BASE_URL"))}


@app.post("/api/rank")
def rank(req: RankingRequest):
    """Relay/backend action: rank a synthetic borrower snapshot locally or via Lambda."""
    try:
        return ranking_gateway.rank_borrowers(req.borrowers)
    except RankingInputError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ranking_gateway.RankingGatewayError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/remind")
def remind(req: Reminder):
    if req.language not in LANGS:
        raise HTTPException(400, f"language must be one of {list(LANGS)}")
    if not re.fullmatch(r"\d{10}", req.phone):
        raise HTTPException(400, "phone must be 10 digits")
    if req.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    if req.deliver_sms and req.phone == PLACEHOLDER_PHONE:
        raise HTTPException(400, "Enter the borrower's real phone number before texting them the link.")
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
        # The reminder text is also the link's purpose, so the borrower reads it in their own
        # language on Cashfree's pay page.
        link = cashfree.create_link(req.name, req.phone, req.amount, purpose=text[:480],
                                    notify_sms=req.deliver_sms)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e))

    LINKS.append({"link_id": link["link_id"], "link_url": link["link_url"], "name": req.name,
                  "borrower_id": req.borrower_id, "amount": req.amount, "language": req.language,
                  "sms": req.deliver_sms, "created_at": datetime.now(timezone.utc).isoformat()})
    return {"text": text, "text_source": "template" if used_template else "sarvam",
            "audio_b64": audio if req.include_audio else None, "notes": notes, "amount": req.amount,
            "sms_requested": req.deliver_sms, "phone_tail": req.phone[-4:],
            "link_id": link["link_id"], "link_url": link["link_url"], "link_status": link["link_status"]}


@app.get("/api/links")
def links():
    return list(reversed(LINKS[-100:]))


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
