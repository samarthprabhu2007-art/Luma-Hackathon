# Demo backend

The existing FastAPI application and SQLite borrower book are the live backend.
Ranking defaults to the same local engine deployed in Lambda, so the shared AWS
gateway is not required. No training labels are used to rank uploaded books.

Run `python -m pip install -r requirements.txt`, then
`python -m uvicorn app:app --host 0.0.0.0 --port 8000`.
The existing `railway.toml` also supplies the deployment start command.
Set `NEXTPAY_DB` to persistent storage when hosting. Use synthetic data only.

Configuration:

* `RANKING_MODE=local` (default); use `lambda` only after gateway access is verified.
* `RANKING_LAMBDA_URL`: full organizer endpoint, used only in lambda mode.
* `NEXTPAY_ACTION_TOKEN`: private token for collections action endpoints.
* Existing Cashfree sandbox and Sarvam configuration remains in `.env`.

Endpoints:

* `POST /api/book/dataset`: upload the training archive, blind archive, or CSV.
* `GET /api/book`: dashboard records with computed routes and explanations.
* `POST /api/rank`: stateless ranking, body `{"borrowers": [...]}`.
* `GET /api/collections/next`: re-evaluate at current time and select the first callable borrower.
* `POST /api/collections/events`: apply a normalized event and re-rank atomically.
* `GET /api/collections/audit`: recent selections and event decisions.

Collections endpoints require `Authorization: Bearer <NEXTPAY_ACTION_TOKEN>`.
Relay may call these actions after its voice/payment integrations verify results.
The next-borrower response includes identity/recording and lender-approval guardrails.
These requirements must be enforced by the agent before discussing balances.

Payment event example:

```json
{
  "event_type": "VERIFIED_RECEIPT",
  "borrower_id": "B001",
  "payload": {
    "transaction_id": "unique-provider-transaction-id",
    "amount_inr": 300,
    "verified_at_ist": "2026-11-21T14:35:00+05:30"
  }
}
```

Only trusted authenticated callers may submit verified receipts after provider
verification. The raw `/webhook` endpoint remains the existing signature-checking
event log; it does not automatically normalize Cashfree payloads into receipts.
Never derive a receipt from a spoken payment claim or link status alone.
Transaction IDs are persisted in SQLite and conflicting replays return HTTP 409.
The baseline imported balance is trusted; only new post-snapshot transactions
should be submitted. Historical receipts already reflected in that balance must
not be replayed without seeding their transaction IDs first.

Other supported events: `CLAIM_PAID`, `HARDSHIP`, `STOP_CONTACT`, `WRONG_NUMBER`,
`CALLBACK`, `PROMISE_TO_PAY`, and `OUTBOUND_ATTEMPT`. Timestamp events carry their
official snapshot field in `payload`. Optional `as_of_ist` supports synthetic
fixture replay; otherwise current UTC is used, with contact policy evaluated in IST.

The public dashboard/import/OCR and legacy reminder endpoints retain the team's
demo access model. Use a restricted demo deployment; this is not production access
control. No new AWS resources are required.
