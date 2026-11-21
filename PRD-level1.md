# PRD: Level 1 — "Say it in their language, get paid"

Sarvam (language) + Cashfree (money), connected end to end, with a fallback at every step so a sandbox payment always completes.
Deadline: Level 1 done and demo-able by **1:15 PM**. Anything after that is Level 2 (the real PS2 collections logic).

## 1. Goal
One button: pick a borrower → Sarvam writes/speaks the reminder in their language → Cashfree creates a payment link → borrower pays in sandbox → our app shows **PAID**.

## 2. Success criteria (Level 1 is done when ALL are true)
1. A reminder in Hindi (and one more language, e.g. Kannada) is generated through the Sarvam API (translate + text-to-speech, audio plays).
2. A Cashfree sandbox payment link is created through the API and opens in a browser.
3. A sandbox payment on that link succeeds.
4. The app shows PAID, from a webhook or from polling the link status.
5. Total time from click to PAID is under 2 minutes, repeatable 3 times in a row.

## 3. Non-goals (Level 1)
No ranking, no learning, no live phone calls, no Relay canvas, no handwriting reading, no payouts, no fairness proof. Those are Level 2+.

## 4. Flow
```
[Borrower row: name, phone, amount, language]
        |
        v
1. Sarvam /translate   : English template -> hi-IN / kn-IN text
2. Sarvam /text-to-speech : text -> audio (base64 wav), played in the page
        |
        v
3. Cashfree POST /pg/links : create payment link (amount, customer, expiry, notify_url)
        |
        v
4. Show: message text + audio + link + QR code
        |
        v
5. Pay in sandbox (test UPI / test card)
        |
        v
6. Cashfree webhook -> /webhook   (or poll GET /pg/links/{link_id})
        |
        v
7. Status on screen: ACTIVE -> PAID / PARTIALLY_PAID / EXPIRED
```

## 5. Fallback ladder (money must move even if everything else fails)
| If this fails | Do this instead | Still moves money? |
|---|---|---|
| Sarvam TTS (audio) | Show translated text only | Yes |
| Sarvam translate | Use pre-written Hindi/Kannada message templates (hard-coded) | Yes |
| Sarvam entirely | Hard-coded template text, no API | Yes |
| Webhook not arriving (no public URL) | Poll `GET /pg/links/{link_id}` every 3 s | Yes |
| Our web app breaks | Run `cashfree_link.py` / curl from terminal, open link, pay | Yes |
| Our code breaks entirely | Create the link by hand in the Cashfree test dashboard (Payment Links) and pay it | Yes |
| Relay is flaky | We do not depend on Relay at Level 1 | Yes |

Rule: Cashfree is the only hard dependency. Sarvam is required to be integrated, but its failure never blocks the payment.

## 6. Tech (keep it boring)
- Python 3 + FastAPI (or Flask) backend, one HTML page, no database (in-memory dict, or a JSON file).
- Secrets in `.env`: `CASHFREE_CLIENT_ID`, `CASHFREE_CLIENT_SECRET`, `SARVAM_API_KEY`. Never commit or paste them in chat.
- Public webhook URL: `ngrok http 8000` (or skip and poll).
- Use Cashfree **test** keys only (`https://sandbox.cashfree.com`).

## 7. API cheat sheet (verify against the docs, versions change)
**Cashfree** (base `https://sandbox.cashfree.com/pg`)
- Headers: `x-client-id`, `x-client-secret`, `x-api-version: 2023-08-01`, `Content-Type: application/json`
- Create link: `POST /links`
  ```json
  {
    "link_id": "L1_<unique>",
    "link_amount": 500,
    "link_currency": "INR",
    "link_purpose": "Loan EMI reminder",
    "customer_details": {"customer_name": "Test User", "customer_phone": "9999999999"},
    "link_partial_payments": true,
    "link_minimum_partial_amount": 100,
    "link_expiry_time": "<ISO8601, 1 day ahead>",
    "link_meta": {"notify_url": "https://<ngrok>/webhook"}
  }
  ```
  Response has `link_url` and `link_status`.
- Check status: `GET /links/{link_id}` -> `link_status` (ACTIVE, PAID, PARTIALLY_PAID, EXPIRED, CANCELLED)
- Sandbox payment: test UPI `success@upi`, or the test card shown on the checkout page (check the Cashfree test-data page for current values).
- Fallback if `/links` is not enabled: `POST /orders` then open checkout with the returned `payment_session_id`.

**Sarvam** (base `https://api.sarvam.ai`, header `api-subscription-key: <key>`)
- Translate: `POST /translate` `{ "input": "...", "source_language_code": "en-IN", "target_language_code": "hi-IN", "model": "<current translate model>" }`
- Text to speech: `POST /text-to-speech` `{ "text": "...", "target_language_code": "hi-IN", "speaker": "<a listed speaker>", "model": "<current bulbul model>" }` -> `audios[0]` is base64 wav.
- Check the Sarvam docs / ask the Sarvam team for current model names and the language list before choosing demo languages.

## 8. Message template (English source)
"Hello {name}, this is a reminder from {lender}. Your payment of Rs {amount} is due. You can pay safely using this link. This call is recorded. If you need help, reply and we will find an option that works for you."
(Keep the tone kind and free of pressure. The "recorded" line prepares for Level 2 compliance.)

## 9. Test plan
1. Link only: run the Cashfree script, open the link, pay with test UPI, confirm PAID in the dashboard. (Do this FIRST, 15 minutes.)
2. Sarvam only: translate + TTS to Hindi, save wav, play it.
3. Joined: click button, all steps, PAID on screen.
4. Failure drill: unset `SARVAM_API_KEY` and confirm the payment still works with the template text.
5. Repeat 3 times.

## 10. Risks
| Risk | Mitigation |
|---|---|
| Payment Links not enabled on the test account | Use Orders + checkout, or ask the Relay/onboarding desk |
| Sarvam credits not yet handed out | Hard-coded template text until they arrive |
| No public webhook URL | Polling |
| API version or model name changed | Read the response error, fix, and check the docs |
| Keys leaked | `.env` only, rotate if pasted anywhere |

## 11. Task split

### If 2 people
- **A (Money, owns the critical path):** Cashfree create link, status polling, webhook, sandbox payment test, fallback script.
- **B (Language and UI):** Sarvam translate + TTS, templates, the one HTML page (button, text, audio, link, QR, status), then wires A's function in.

### If 3 people (recommended)
- **A (Money):** Cashfree create link, status polling, webhook, test payments.
- **B (Language):** Sarvam translate + TTS, templates for 2 languages, language fallback.
- **C (Glue and demo):** FastAPI skeleton, HTML page, `.env`, ngrok, end-to-end test, failure drills, demo script.

### If 5 people
1. **Money core:** Cashfree create link + status + sandbox pay test.
2. **Webhook and status:** webhook endpoint, ngrok, polling fallback, status display.
3. **Language:** Sarvam translate + TTS, 2 languages.
4. **App shell:** FastAPI + HTML page, button, audio player, QR, `.env`.
5. **QA and Level 2 prep:** failure drills, 3x repeat test, demo script, and start the synthetic borrower book (Level 2 data).

## 12. Timeline
| Time | Milestone |
|---|---|
| 12:15 | Everyone has keys and a repo. Smoke tests start (Cashfree link by hand, Sarvam hello world). |
| 12:45 | Money core: API creates a link and you can pay it. Language: Hindi audio plays. |
| 1:15 | Joined flow works end to end, PAID shows on screen. **Level 1 done.** |
| 1:15 onward | Move to Level 2 (ranking, the call, the re-forming queue). |

## 13. Handoff to Level 2
Level 1 pieces become Level 2 building blocks: the link function (add partial payment for hardship), the webhook (feeds re-ranking), the Sarvam message step (becomes the call script).
