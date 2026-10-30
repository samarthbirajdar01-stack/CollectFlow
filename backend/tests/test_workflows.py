from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from database import SessionLocal
from main import _backfill_audit_logs, app
from models import FollowUp, PaymentPromise


def expected_priority(account, calls, accounts):
    eligible = [row for row in accounts if row["priority_eligible"]]
    max_balance = max(row["outstanding_amount"] for row in eligible)
    max_dpd = max(row["days_past_due"] for row in eligible)
    outcome_scores = {"NOT_REACHABLE": 1.0, "PROMISED_TO_PAY": 0.65, "DISPUTE": 0.0, "PAID": 0.0}
    contact = sum(outcome_scores.get(call["outcome"], 0.5) for call in calls) / len(calls) if calls else 0.5
    return round(
        account["outstanding_amount"] / max_balance * 40
        + account["days_past_due"] / max_dpd * 35
        + contact * 25,
        1,
    )


def test_critical_collection_workflows():
    with TestClient(app) as client:
        agents = client.get("/api/agents").json()
        assert agents
        agent_id = agents[0]["id"]

        accounts = client.get("/api/accounts").json()
        customers = client.get("/api/customers").json()
        calls = client.get("/api/calls?limit=500").json()
        payments = client.get("/api/payments?limit=500").json()
        imported_audits = client.get("/api/audit-logs?limit=500").json()
        assert len(accounts) >= 30
        assert len(customers) >= 30
        assert len(calls) >= 50
        assert len(payments) >= 30
        assert sum(entry["event_type"] == "CALL_IMPORTED" for entry in imported_audits) == len(calls)
        assert sum(entry["event_type"] == "PAYMENT_IMPORTED" for entry in imported_audits) == len(payments)
        initial_audit_count = len(imported_audits)
        _backfill_audit_logs()
        assert len(client.get("/api/audit-logs?limit=500").json()) == initial_audit_count
        assert all(
            not account["priority_eligible"]
            for account in accounts[len([row for row in accounts if row["priority_eligible"]]):]
        )
        assert accounts == sorted(accounts, key=lambda row: (
            row["priority_eligible"], row["priority_score"], row["outstanding_amount"]
        ), reverse=True)

        eligible = [row for row in accounts if row["priority_eligible"] and row["outstanding_amount"] > 100]
        target = next(row for row in eligible if row["days_past_due"] < 36500)
        history = client.get(f"/api/calls?loan_id={target['id']}").json()
        assert target["priority_score"] == expected_priority(target, history, accounts)

        changed = client.patch(f"/api/accounts/{target['id']}", json={
            "days_past_due": target["days_past_due"] + 3,
        })
        assert changed.status_code == 200
        refreshed_accounts = client.get("/api/accounts").json()
        refreshed = next(row for row in refreshed_accounts if row["id"] == target["id"])
        refreshed_history = client.get(f"/api/calls?loan_id={target['id']}").json()
        assert refreshed["priority_score"] == expected_priority(refreshed, refreshed_history, refreshed_accounts)
        assert client.patch(f"/api/accounts/{target['id']}", json={}).status_code == 422

        balance_account = next(row for row in refreshed_accounts if row["priority_eligible"] and row["outstanding_amount"] > 100)
        starting_balance = Decimal(str(balance_account["outstanding_amount"]))
        partial_amount = Decimal("10.25")
        partial = client.post("/api/payments", json={
            "loan_id": balance_account["id"],
            "agent_id": agent_id,
            "amount": str(partial_amount),
            "method": "Test ACH",
        })
        assert partial.status_code == 201, partial.text
        assert Decimal(str(partial.json()["amount"])) == partial_amount
        partial_balance = client.get("/api/accounts").json()
        updated_balance = Decimal(str(next(row for row in partial_balance if row["id"] == balance_account["id"])["outstanding_amount"]))
        assert updated_balance == starting_balance - partial_amount
        assert any(row["id"] == partial.json()["id"] for row in client.get(f"/api/payments?loan_id={balance_account['id']}").json())
        partial_row = next(row for row in partial_balance if row["id"] == balance_account["id"])
        partial_history = client.get(f"/api/calls?loan_id={balance_account['id']}").json()
        assert partial_row["priority_score"] == expected_priority(partial_row, partial_history, partial_balance)

        overpayment = client.post("/api/payments", json={
            "loan_id": balance_account["id"], "amount": str(updated_balance + Decimal("0.01")),
        })
        invalid_precision = client.post("/api/payments", json={
            "loan_id": balance_account["id"], "amount": "1.001",
        })
        invalid_future_date = client.post("/api/payments", json={
            "loan_id": balance_account["id"],
            "amount": "1.00",
            "paid_at": (datetime.now() + timedelta(days=1)).isoformat(),
        })
        assert overpayment.status_code == 422
        assert invalid_precision.status_code == 422
        assert invalid_future_date.status_code == 422
        blank_method = client.post("/api/payments", json={
            "loan_id": balance_account["id"], "amount": "1.00", "method": "   ",
        })
        assert blank_method.status_code == 422

        final_payment = client.post("/api/payments", json={
            "loan_id": balance_account["id"], "amount": str(updated_balance), "agent_id": agent_id,
        })
        assert final_payment.status_code == 201
        paid_account = next(row for row in client.get("/api/accounts").json() if row["id"] == balance_account["id"])
        assert paid_account["outstanding_amount"] == 0
        assert paid_account["status"] == "PAID"
        assert not paid_account["priority_eligible"]

        promise_account = next(row for row in client.get("/api/accounts").json() if row["priority_eligible"] and row["outstanding_amount"] > 200)
        promise_call = client.post("/api/calls", json={
            "loan_id": promise_account["id"],
            "agent_id": agent_id,
            "outcome": "PROMISED_TO_PAY",
            "notes": "Synthetic promise for API workflow test",
            "promise_date": (date.today() + timedelta(days=2)).isoformat(),
        })
        assert promise_call.status_code == 201, promise_call.text
        after_promise_accounts = client.get("/api/accounts").json()
        after_promise_account = next(row for row in after_promise_accounts if row["id"] == promise_account["id"])
        after_promise_calls = client.get(f"/api/calls?loan_id={promise_account['id']}").json()
        assert after_promise_account["priority_score"] == expected_priority(
            after_promise_account, after_promise_calls, after_promise_accounts,
        )
        promise = next(
            row for row in client.get(f"/api/promises?loan_id={promise_account['id']}").json()
            if row["call_id"] == promise_call.json()["id"]
        )
        assert promise["status"] == "PENDING"
        promise_followup = next(
            item for item in client.get("/api/followups?status=ALL").json()
            if item["promise_id"] == promise["id"]
        )
        assert promise_followup["status"] == "OPEN"
        honored_payment = client.post("/api/payments", json={
            "loan_id": promise_account["id"], "agent_id": agent_id, "amount": "1.00",
        })
        assert honored_payment.status_code == 201
        honored = next(
            row for row in client.get(f"/api/promises?loan_id={promise_account['id']}").json()
            if row["call_id"] == promise_call.json()["id"]
        )
        assert honored["status"] == "KEPT"
        assert honored["payment_id"] == honored_payment.json()["id"]
        assert next(item for item in client.get("/api/followups?status=ALL").json() if item["id"] == promise_followup["id"])["status"] == "COMPLETED"

        missed_account = next(row for row in client.get("/api/accounts").json() if row["priority_eligible"] and row["outstanding_amount"] > 200 and row["id"] != promise_account["id"])
        missed_call = client.post("/api/calls", json={
            "loan_id": missed_account["id"],
            "agent_id": agent_id,
            "outcome": "PROMISED_TO_PAY",
            "notes": "Synthetic missed commitment test",
            "promise_date": (date.today() + timedelta(days=3)).isoformat(),
        })
        assert missed_call.status_code == 201
        with SessionLocal() as db:
            missed_promise = db.query(PaymentPromise).filter_by(call_id=missed_call.json()["id"]).one()
            missed_promise.due_at = datetime.now() - timedelta(seconds=1)
            db.commit()
        assert next(row for row in client.get(f"/api/promises?loan_id={missed_account['id']}").json() if row["call_id"] == missed_call.json()["id"])["status"] == "MISSED"
        assert next(row for row in client.get("/api/followups?status=MISSED").json() if row["loan_id"] == missed_account["id"])["status"] == "MISSED"

        logged_call = client.post("/api/calls", json={
            "loan_id": missed_account["id"],
            "agent_id": agent_id,
            "outcome": "NOT_REACHABLE",
            "notes": "Call history audit test",
        })
        assert logged_call.status_code == 201
        stored_call = next(row for row in client.get(f"/api/calls?loan_id={missed_account['id']}").json() if row["id"] == logged_call.json()["id"])
        assert stored_call["notes"] == "Call history audit test"
        assert stored_call["contacted_at"]
        blank_call = client.post("/api/calls", json={
            "loan_id": missed_account["id"],
            "agent_id": agent_id,
            "outcome": "NOT_REACHABLE",
            "notes": "   ",
        })
        assert blank_call.status_code == 422
        after_call_accounts = client.get("/api/accounts").json()
        after_call_account = next(row for row in after_call_accounts if row["id"] == missed_account["id"])
        after_call_history = client.get(f"/api/calls?loan_id={missed_account['id']}").json()
        assert after_call_account["priority_score"] == expected_priority(
            after_call_account, after_call_history, after_call_accounts,
        )

        disputed = client.post("/api/calls", json={
            "loan_id": missed_account["id"],
            "agent_id": agent_id,
            "outcome": "DISPUTE",
            "notes": "Synthetic dispute test",
        })
        assert disputed.status_code == 201
        flagged = next(row for row in client.get("/api/accounts").json() if row["id"] == missed_account["id"])
        assert not flagged["priority_eligible"] and flagged["requires_review"]
        assert "Account is in dispute" in flagged["review_reasons"]
        blocked = client.post("/api/calls", json={
            "loan_id": missed_account["id"],
            "agent_id": agent_id,
            "outcome": "NOT_REACHABLE",
            "notes": "Outreach must require review",
        })
        assert blocked.status_code == 409

        restriction = client.patch(f"/api/accounts/{target['id']}", json={"contact_restricted": True})
        assert restriction.status_code == 200
        assert not restriction.json()["priority_eligible"]
        assert restriction.json()["requires_review"]
        account_audits = client.get(f"/api/audit-logs?loan_id={target['id']}").json()
        assert any(row["event_type"] == "ACCOUNT_UPDATED" for row in account_audits)
        payment_audits = client.get(f"/api/audit-logs?loan_id={balance_account['id']}").json()
        assert sum(row["event_type"] == "PAYMENT_RECORDED" for row in payment_audits) >= 2
        assert any(row["event_type"] == "CALL_RECORDED" for row in client.get(f"/api/audit-logs?loan_id={missed_account['id']}").json())
        audit_count_before_backfill = len(client.get("/api/audit-logs?limit=500").json())
        _backfill_audit_logs()
        assert len(client.get("/api/audit-logs?limit=500").json()) == audit_count_before_backfill

        analytics = client.get("/api/analytics").json()
        assert 0 <= analytics["recovery_rate"] <= 100
        assert analytics["total_payments"] == len(client.get("/api/payments?limit=500").json())
        assert analytics["pending_promises"] + analytics["kept_promises"] + analytics["missed_promises"] == analytics["total_promises"]
        assert 0 <= analytics["promise_to_pay_conversion_rate"] <= 100
        assert client.get("/api/accounts?status=INVALID").status_code == 422
        assert client.get("/api/promises?status=INVALID").status_code == 422
        assert client.get("/api/customers/999999").status_code == 404
        assert client.get("/api/reports/collections.csv").status_code == 200
