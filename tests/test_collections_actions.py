import csv
import io

import pytest
from fastapi.testclient import TestClient

import app
from shared_book import load_csv


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('NEXTPAY_DB', str(tmp_path / 'test.sqlite3'))
    monkeypatch.setenv('RANKING_MODE', 'local')
    monkeypatch.setenv('NEXTPAY_ACTION_TOKEN', 'synthetic-test-token')
    snapshot = dict(borrower_id='B001', loan_number='LN001', as_of_ist='2026-11-21T14:30:00+05:30',
                    outstanding_inr=1000, prior_payments_after_reminders=1, prior_unaided_payments=0,
                    display_name='Synthetic Borrower', language_code='hi-IN', original_order=1)
    content = io.StringIO()
    writer = csv.DictWriter(content, fieldnames=list(snapshot))
    writer.writeheader()
    writer.writerow(snapshot)
    content.seek(0)
    assert load_csv(content) == 1
    return TestClient(app.app)


HEADERS = {'Authorization': 'Bearer synthetic-test-token'}


def receipt(tx='TX001', amount=300):
    return dict(event_type='VERIFIED_RECEIPT', borrower_id='B001',
                as_of_ist='2026-11-21T14:40:00+05:30',
                payload=dict(transaction_id=tx, amount_inr=amount,
                             verified_at_ist='2026-11-21T14:35:00+05:30'))


def test_import_uses_inputs_without_training_labels(client):
    book = client.get('/api/book').json()
    assert book[0]['score'] == 1
    assert book[0]['route'] == 'CALL'


def test_receipt_replay_and_conflicting_replay(client):
    first = client.post('/api/collections/events', json=receipt(), headers=HEADERS)
    assert first.status_code == 200
    assert first.json()['outstanding_inr'] == 700
    second = client.post('/api/collections/events', json=receipt(), headers=HEADERS)
    assert second.json()['duplicate'] is True
    assert second.json()['outstanding_inr'] == 700
    assert client.post('/api/collections/events', json=receipt(amount=400), headers=HEADERS).status_code == 409
    final = client.post('/api/collections/events', json=receipt('TX002', 700), headers=HEADERS).json()
    assert final['outstanding_inr'] == 0
    assert final['ranking']['excluded'][0]['route'] == 'CLOSE_PAID'
    assert client.post('/api/collections/events', json=receipt(), headers=HEADERS).json()['outstanding_inr'] == 0


def test_claim_pauses_without_changing_balance(client):
    event = dict(event_type='CLAIM_PAID', borrower_id='B001', as_of_ist='2026-11-21T14:40:00+05:30')
    response = client.post('/api/collections/events', json=event, headers=HEADERS).json()
    assert response['outstanding_inr'] == 1000
    assert response['ranking']['excluded'][0]['route'] == 'RECONCILE_CLAIM'


def test_action_requires_authentication(client):
    assert client.post('/api/collections/events', json=receipt()).status_code == 401
