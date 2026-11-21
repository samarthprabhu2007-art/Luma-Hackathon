"""Authenticated actions for the existing synthetic borrower book."""
import hmac
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException

from shared_book import database, rerank
from lambda_backend.ranking import RankingInputError, _moment
from ranking_gateway import RankingGatewayError

router = APIRouter(prefix='/api/collections')


def authorize(authorization: str = Header(default='')):
    token = os.getenv('NEXTPAY_ACTION_TOKEN', '')
    if not token or not hmac.compare_digest(authorization, 'Bearer ' + token):
        raise HTTPException(401, 'A configured action token is required.')


def audit(db, event):
    db.execute('INSERT INTO audit(at,event) VALUES(?,?)',
               (datetime.now(timezone.utc).isoformat(), json.dumps(event)))


@router.get('/next', dependencies=[Depends(authorize)])
def next_borrower():
    with database() as db:
        decisions = rerank(db, datetime.now(timezone.utc).isoformat())
        if not decisions['ranked']:
            return {'borrower': None, 'summary': decisions['summary']}
        selected = decisions['ranked'][0]
        snapshots = [json.loads(r[0]) for r in db.execute('SELECT snapshot FROM borrowers WHERE snapshot IS NOT NULL')]
        snapshot = next(r for r in snapshots if r['borrower_id'] == selected['borrower_id'])
        audit(db, {'type': 'BORROWER_SELECTED', 'decision': selected})
        return {'decision': selected, 'borrower': snapshot,
                'guardrails': {'identity_verification_required': True,
                               'recording_disclosure_required': True,
                               'loan_term_changes_require_lender_approval': True}}


@router.post('/events', dependencies=[Depends(authorize)])
def apply_event(event: dict):
    """Trusted normalized actions; raw payment claims cannot alter money."""
    try:
        event_type = event.get('event_type')
        borrower_id = event.get('borrower_id')
        payload = event.get('payload', {})
        if not isinstance(payload, dict):
            raise HTTPException(422, 'payload must be an object')
        at = event.get('as_of_ist')
        if not at:
            at = datetime.now(timezone.utc).isoformat()
        _moment({'at': at}, 'at', required=True)
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            found = None
            for key, raw in db.execute('SELECT id,snapshot FROM borrowers WHERE snapshot IS NOT NULL'):
                snapshot = json.loads(raw)
                if snapshot['borrower_id'] == borrower_id:
                    found = key, snapshot
                    break
            if found is None:
                raise HTTPException(404, 'Unknown borrower_id')
            key, snapshot = found
            duplicate = False
            if event_type == 'VERIFIED_RECEIPT':
                tx = payload.get('transaction_id')
                amount = payload.get('amount_inr')
                if not isinstance(tx, str) or not tx.strip() or type(amount) is not int or amount <= 0:
                    raise HTTPException(422, 'A transaction_id and positive integer amount_inr are required.')
                verified = payload.get('verified_at_ist')
                verified_time = _moment({'verified': verified}, 'verified', required=True)
                if verified_time > _moment({'at': at}, 'at', required=True):
                    raise HTTPException(422, 'Receipt verification cannot be after the event cutoff.')
                existing = db.execute('SELECT borrower,amount,verified_at FROM receipts WHERE transaction_id=?', (tx,)).fetchone()
                if existing:
                    if existing != (borrower_id, amount, verified):
                        raise HTTPException(409, 'Conflicting transaction replay')
                    duplicate = True
                else:
                    db.execute('INSERT INTO receipts VALUES(?,?,?,?)', (tx, borrower_id, amount, verified))
                    snapshot['outstanding_inr'] = max(0, int(snapshot['outstanding_inr']) - amount)
                    snapshot['verified_received_inr'] = int(snapshot.get('verified_received_inr') or 0) + amount
                    snapshot['balance_checked_at_ist'] = verified
                    if snapshot['outstanding_inr'] == 0:
                        snapshot['unverified_payment_claim'] = 0
            elif event_type in {'CLAIM_PAID', 'HARDSHIP', 'STOP_CONTACT', 'WRONG_NUMBER'}:
                field = {'CLAIM_PAID': 'unverified_payment_claim', 'HARDSHIP': 'hardship_open',
                         'STOP_CONTACT': 'stop_contact', 'WRONG_NUMBER': 'wrong_number'}[event_type]
                snapshot[field] = 1
            elif event_type in {'CALLBACK', 'PROMISE_TO_PAY', 'OUTBOUND_ATTEMPT'}:
                field = {'CALLBACK': 'requested_callback_at_ist', 'PROMISE_TO_PAY': 'active_promise_due_ist',
                         'OUTBOUND_ATTEMPT': 'last_outbound_attempt_ist'}[event_type]
                _moment(payload, field, required=True)
                snapshot[field] = payload[field]
            else:
                raise HTTPException(422, 'Unsupported event_type')
            db.execute('UPDATE borrowers SET snapshot=? WHERE id=?', (json.dumps(snapshot), key))
            decisions = rerank(db, at)
            audit(db, {'event_type': event_type, 'borrower_id': borrower_id,
                       'transaction_id': payload.get('transaction_id'), 'duplicate': duplicate})
            return {'duplicate': duplicate, 'ranking': decisions,
                    'outstanding_inr': int(snapshot['outstanding_inr'])}
    except RankingInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RankingGatewayError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get('/audit', dependencies=[Depends(authorize)])
def events():
    with database() as db:
        return [{'at': at, **json.loads(event)} for at, event in db.execute(
            'SELECT at,event FROM audit ORDER BY sequence DESC LIMIT 100')]
