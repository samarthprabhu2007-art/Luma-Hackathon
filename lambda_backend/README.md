# Ranking Lambda

Dependency-free Python backend for Part B of the Collections Prioritization Agent.
It accepts the official `borrowers.csv` field names from the NextPay training and
held-out books.

## Handler

`lambda_backend.ranking.lambda_handler`

## Supported actions

- `rank`: applies the official ordered routing gates, scores `CALL` borrowers,
  and returns a deterministic queue with audit reasons.
- `swap_test`: swaps only protected presentation fields and proves the ranking result is unchanged.

The due-callback flag is derived from `requested_callback_at_ist` and
`as_of_ist`. The scorer then uses only that flag,
`prior_payments_after_reminders`, and `prior_unaided_payments`. Display name,
service language, display area, transcript, balance, and loan number never feed
the score.

Routing follows the data dictionary exactly: paid, opt-out, wrong-number,
hardship, reconciliation, promise, callback, agreed follow-up, calling window,
and 24-hour cooldown gates run before scoring. Calling hours are `[08:00,
19:00)` India time.

## AWS settings

- Runtime: Python 3.12
- Architecture: x86_64 or arm64
- Handler: `lambda_backend.ranking.lambda_handler`
- Timeout: 10 seconds
- Memory: 128 MB
- Environment variables: none for the first version
- Execution role: `saamarths-cs25-exec`

Deploy the repository ZIP with `lambda_backend/__init__.py` and
`lambda_backend/ranking.py` at their current paths. No Lambda Function URL is
needed; use the hackathon-provided call URL.

## Existing backend adapter

`ranking_gateway.py` posts the handler's direct event shape to the full
organizer-provided invocation URL. It accepts either a direct Lambda result or
the handler's HTTP proxy envelope. Set `RANKING_LAMBDA_URL` to enable the remote
call. When it is empty, the adapter uses this same local ranking engine and
makes no external request.
