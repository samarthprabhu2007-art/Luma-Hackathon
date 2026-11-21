"""Read a borrower-list scan with Sarvam Document AI for human review."""
import asyncio
import os
from io import BytesIO
from typing import Literal
from urllib.parse import quote
from zipfile import BadZipFile, ZipFile

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
MAX_BYTES = 8 * 1024 * 1024
FORMATS = {
    "image/png": ("png", b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": ("jpg", b"\xff\xd8\xff"),
    "application/pdf": ("pdf", b"%PDF-"),
}


async def read_scan(request: Request, mime: str) -> bytes:
    if mime not in FORMATS:
        raise HTTPException(415, "Choose a PNG, JPEG or PDF document.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, "The scan exceeds 8 MB. Upload a smaller file.")
        body.extend(chunk)
    if not body.startswith(FORMATS[mime][1]):
        raise HTTPException(422, "The file does not match its selected format.")
    return bytes(body)


async def parse_scan(client: httpx.AsyncClient, data: bytes, mime: str, language: str) -> str:
    response = await client.post(
        "parse", files={"file": (f"scan.{FORMATS[mime][0]}", data, mime)},
        data={"language": language, "output_format": "md"},
    )
    response.raise_for_status()
    job = quote(response.json()["job_id"], safe="")
    while True:
        response = await client.get(f"{job}/status")
        response.raise_for_status()
        state = response.json()["status"].lower()
        if state == "completed":
            break
        if state in {"failed", "rejected", "partially_completed", "cancelled"}:
            raise HTTPException(422, "Sarvam could not read the complete document. Try a clearer scan.")
        await asyncio.sleep(2)

    archive = BytesIO()
    async with client.stream("GET", f"{job}/results", params={"format": "md"}) as result:
        result.raise_for_status()
        async for chunk in result.aiter_bytes():
            if archive.tell() + len(chunk) > 16 * 1024 * 1024:
                raise HTTPException(422, "OCR output is too large. Split the scan into smaller files.")
            archive.write(chunk)
    with ZipFile(archive) as output:
        docs = [entry for entry in output.infolist() if entry.filename.endswith(".md")]
        if sum(entry.file_size for entry in docs) > 1024 * 1024:
            raise HTTPException(422, "Too much extracted text. Split the list into smaller files.")
        text = "\n\n".join(output.read(entry).decode("utf-8-sig") for entry in docs).strip()
    if not text:
        raise HTTPException(422, "No readable text was found in this scan.")
    return text


@router.post("/api/lender/ocr")
async def read_list(request: Request, language: Literal["en-IN", "hi-IN", "kn-IN", "ta-IN", "te-IN"] = "en-IN"):
    mime = request.headers.get("content-type", "").partition(";")[0].lower()
    data = await read_scan(request, mime)
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise HTTPException(503, "Configure the Sarvam API key to read scans.")
    try:
        async with httpx.AsyncClient(base_url="https://api.sarvam.ai/doc-ai/v1/job/",
                                     headers={"api-subscription-key": key}, timeout=30) as client:
            text = await asyncio.wait_for(parse_scan(client, data, mime, language), timeout=150)
    except (TimeoutError, httpx.TimeoutException):
        raise HTTPException(504, "Sarvam took too long to read the scan. Try a smaller document.") from None
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise HTTPException(502, f"Sarvam OCR returned HTTP {status}. Check document access, credits and file format.") from None
    except (httpx.RequestError, KeyError, ValueError, TypeError, BadZipFile):
        raise HTTPException(502, "The Sarvam OCR response could not be read. Try again.") from None
    return {"text": text, "confidence": None}
