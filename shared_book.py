"""One database per app deployment. Mount NEXTPAY_DB on persistent storage."""

import csv

import io

import json

import os

import sqlite3

import sys

import zipfile

from contextlib import contextmanager

from datetime import datetime, timezone

from pathlib import Path



from fastapi import APIRouter, HTTPException, Request, Response

from pydantic import BaseModel, Field

from lender_ocr import read_scan



router = APIRouter(prefix="/api/book")



@contextmanager

def database():

    path = Path(os.environ.get("NEXTPAY_DB") or Path(__file__).with_name("data") / "nextpay.sqlite3")

    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, timeout=30)

    try:

        with conn:

            conn.executescript("""

            CREATE TABLE IF NOT EXISTS borrowers(id TEXT PRIMARY KEY COLLATE NOCASE, position INTEGER, record TEXT, snapshot TEXT);

            CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY, mime TEXT, content BLOB);

            CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, borrower TEXT, at TEXT, text TEXT, staff TEXT, scan TEXT);

            """)

            yield conn

    finally:

        conn.close()



def load_dataset(path):

    with zipfile.ZipFile(path) as archive, archive.open("borrowers.csv") as file:

        return load_csv(io.TextIOWrapper(file, encoding="utf-8-sig"))



def load_csv(file):

    with database() as db:

        added = 0

        for r in csv.DictReader(file):

            route = r["expected_route"]

            status = "Eligible" if route == "CALL" else "Scheduled" if route.startswith("WAIT") else "Human review" if r["hardship_open"] == "1" else "Paused"

            reason = r["score_reason"]

            row = dict(id=r["loan_number"], name=r["display_name"], balance=float(r["outstanding_inr"]), status=status,

                       language=r["language_code"], score=int(r["priority_score"]) if r["priority_score"] else None,

                       action=reason, reason=reason, outcome=r["last_intent"], owner="Unassigned",

                       due=r["next_agreed_followup_ist"] or r["requested_callback_at_ist"] or r["active_promise_due_ist"], history=[])

            position = int(r["expected_rank"]) if r["expected_rank"] else 100000+int(r["original_order"])

            added += db.execute("INSERT OR IGNORE INTO borrowers VALUES(?,?,?,?)",(row["id"],position,json.dumps(row),json.dumps(r))).rowcount

        return added



@router.get("")

def book():

    with database() as db:

        rows = {key:json.loads(data) for key,data in db.execute("SELECT id,record FROM borrowers ORDER BY position,id")}

        for key,at,text,staff,scan in db.execute("SELECT borrower,at,text,staff,scan FROM notes ORDER BY at DESC"):

            if key in rows:

                rows[key]["history"].append(dict(at=at,title="Handwritten log",detail=staff+" · "+text,scan=scan))

        return list(rows.values())



@router.put("/scans/{scan_id}")

async def upload(scan_id: str, request: Request):

    mime = request.headers.get("content-type","").partition(";")[0]

    data = await read_scan(request,mime)

    with database() as db:

        db.execute("INSERT OR IGNORE INTO scans VALUES(?,?,?)",(scan_id,mime,data))

    return {"saved":True}



@router.get("/scans/{scan_id}")

def scan(scan_id: str):

    with database() as db:

        row=db.execute("SELECT mime,content FROM scans WHERE id=?",(scan_id,)).fetchone()

        if not row:

            raise HTTPException(404,"Scan missing")

        return Response(row[1],media_type=row[0],headers={"X-Content-Type-Options":"nosniff"})



class Note(BaseModel):

    text: str = Field(min_length=1,max_length=50000)

    staff: str = Field(min_length=1,max_length=200)

    scan: str



@router.post("/{loan}/logs")

def add_log(loan: str, note: Note):

    with database() as db:

        key=db.execute("SELECT id FROM borrowers WHERE id=?",(loan,)).fetchone()

        if not key or not db.execute("SELECT 1 FROM scans WHERE id=?",(note.scan,)).fetchone():

            raise HTTPException(404,"Borrower or source scan missing")

        db.execute("INSERT OR IGNORE INTO notes VALUES(?,?,?,?,?,?)",(note.scan,key[0],datetime.now(timezone.utc).isoformat(),note.text,note.staff,note.scan))

    return {"saved":True}



@router.post("")

def import_rows(rows:list[dict]):

    added=0

    with database() as db:

        for row in rows:

            if not row.get("id") or not row.get("name") or row.get("status") not in {"Eligible","Paused","Scheduled","Human review"}:

                raise HTTPException(422,"Incomplete borrower")

            row.update(history=[],score=None,outcome="List entry confirmed")

            added+=db.execute("INSERT OR IGNORE INTO borrowers VALUES(?,?,?,NULL)",(row["id"],1000000,json.dumps(row))).rowcount

    return {"added":added,"skipped":len(rows)-added}



if __name__ == "__main__":

    load_dataset(sys.argv[1])



@router.post("/dataset")

async def upload_dataset(request: Request):

    body = bytearray()

    async for chunk in request.stream():

        if len(body) + len(chunk) > 24 * 1024 * 1024:

            raise HTTPException(413, "Choose a dataset under 24 MB")

        body.extend(chunk)

    try:

        if body.startswith(b"PK"):

            with zipfile.ZipFile(io.BytesIO(body)) as archive:

                if archive.getinfo("borrowers.csv").file_size > 32 * 1024 * 1024:

                    raise HTTPException(413, "Borrower table too large")

            added = load_dataset(io.BytesIO(body))

        else:

            added = load_csv(io.StringIO(body.decode("utf-8-sig")))

    except (KeyError, ValueError, csv.Error, zipfile.BadZipFile):

        raise HTTPException(422, "Choose the NextPay training archive or its borrowers.csv")

    return {"added": added}
