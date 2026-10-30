import math
from datetime import date, datetime, time, timedelta

from fastapi.testclient import TestClient

from database import SessionLocal, engine
from main import app
from models import CallLog, Customer, FollowUp, Loan, Payment, PaymentPromise


def test_api_routes_cors_and_database_derived_metrics():
    with TestClient(app) as client:
        origin = "http://localhost:5173"
        preflight = client.options(
            "/api/dashboard",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == origin

        assert client.get("/api/health").json()["status"] == "ok"
        agents = client.get("/api/agents").json()
        assert agents
        agent_id = agents[0]["id"]
        accounts = client.get("/api/accounts").json()
        customers = client.get("/api/customers").json()
        assert client.get("/api/accounts?status=ALL&review=false&search=").status_code == 200
        assert client.get("/api/customers?search=").status_code == 200
        assert client.get(f"/api/customers/{customers[0]['id']}").status_code == 200
        assert client.get("/api/calls?limit=500").status_code == 200
        assert client.get("/api/followups?period=all&status=ALL").status_code == 200
        assert client.get("/api/followups?period=today&status=OPEN").status_code == 200
        assert client.get("/api/followups?period=upcoming&status=OPEN").status_code == 200
        assert client.get("/api/followups?period=overdue&status=OPEN").status_code == 200
        assert client.get("/api/payments?limit=500").status_code == 200
        assert client.get("/api/promises?status=ALL").status_code == 200
        assert client.get("/api/promises?status=PENDING").status_code == 200
        assert client.get("/api/audit-logs?limit=500").status_code == 200
        assert client.get("/api/analytics").status_code == 200
        report = client.get("/api/reports/collections.csv")
        assert report.status_code == 200
        assert report.headers["content-type"].startswith("text/csv")

        dashboard = client.get("/api/dashboard").json()
        analytics = client.get("/api/analytics").json()
        with SessionLocal() as db:
            loans = db.query(Loan).all()
            payments = db.query(Payment).all()
            calls = db.query(CallLog).all()
            promises = db.query(PaymentPromise).all()
            followups = db.query(FollowUp).all()
            today = date.today()
            start_today = datetime.combine(today, time.min)
            tomorrow = datetime.combine(today + timedelta(days=1), time.min)
            start_month = datetime.combine(today.replace(day=1), time.min)
            principal = sum(loan.principal_amount for loan in loans)
            recovered = sum(payment.amount for payment in payments)
            assert dashboard["metrics"]["assigned_accounts"] == len(loans)
            assert dashboard["metrics"]["total_outstanding"] == round(
                sum(loan.outstanding_amount for loan in loans), 2
            )
            assert dashboard["metrics"]["recovered_total"] == round(recovered, 2)
            assert dashboard["metrics"]["recovery_rate"] == round(recovered / principal * 100, 1)
            assert dashboard["metrics"]["recovered_this_month"] == round(
                sum(payment.amount for payment in payments if payment.paid_at >= start_month), 2
            )
            assert dashboard["metrics"]["todays_followups"] == sum(
                task.status == "OPEN" and start_today <= task.due_at < tomorrow
                for task in followups
            )
            assert dashboard["metrics"]["upcoming_followups"] == sum(
                task.status == "OPEN" and task.due_at >= tomorrow
                for task in followups
            )
            assert dashboard["metrics"]["overdue_followups"] == sum(
                task.status == "OPEN" and task.due_at < start_today
                for task in followups
            )
            assert dashboard["metrics"]["overdue_accounts"] == sum(
                loan.outstanding_amount > 0 and loan.days_past_due > 0 and not loan.is_disputed
                for loan in loans
            )
            customers_by_id = {customer.id: customer for customer in db.query(Customer).all()}
            assert dashboard["metrics"]["accounts_needing_review"] == sum(
                loan.outstanding_amount > 0
                and (loan.is_disputed or customers_by_id[loan.customer_id].contact_restricted)
                for loan in loans
            )
            assert analytics["total_calls"] == len(calls)
            assert analytics["total_payments"] == len(payments)
            assert analytics["total_promises"] == len(promises)
            assert analytics["payment_success_rate"] == round(
                sum(call.outcome == "PAID" for call in calls) / len(calls) * 100, 1
            )
            assert math.isclose(
                sum(row["recovered"] for row in dashboard["agent_performance"]),
                recovered,
                abs_tol=0.01,
            )
            resolved_promises = [promise for promise in promises if promise.status != "PENDING"]
            kept_promises = sum(promise.status == "KEPT" for promise in resolved_promises)
            assert analytics["pending_promises"] == sum(promise.status == "PENDING" for promise in promises)
            assert analytics["kept_promises"] == kept_promises
            assert analytics["missed_promises"] == sum(promise.status == "MISSED" for promise in promises)
            assert analytics["promise_to_pay_conversion_rate"] == (
                round(kept_promises / len(resolved_promises) * 100, 1) if resolved_promises else 0
            )

        writable_account = next(
            row for row in accounts
            if row["priority_eligible"] and row["outstanding_amount"] > 100
        )
        followup = client.post("/api/followups", json={
            "loan_id": writable_account["id"],
            "agent_id": agent_id,
            "due_at": (datetime.now() + timedelta(days=1)).isoformat(),
            "kind": "CALL",
            "notes": "Synthetic endpoint inventory task",
        })
        assert followup.status_code == 201, followup.text
        updated_followup = client.patch(
            f"/api/followups/{followup.json()['id']}",
            json={"status": "COMPLETED"},
        )
        assert updated_followup.status_code == 200
        assert updated_followup.json()["status"] == "COMPLETED"
        assert any(
            item["id"] == followup.json()["id"]
            for item in client.get("/api/followups?period=all&status=COMPLETED").json()
        )

        scheduled_call = client.post("/api/calls", json={
            "loan_id": writable_account["id"],
            "agent_id": agent_id,
            "outcome": "NOT_REACHABLE",
            "notes": "Synthetic scheduled callback test",
            "follow_up_at": (datetime.now() + timedelta(days=2)).isoformat(),
        })
        assert scheduled_call.status_code == 201, scheduled_call.text
        assert any(
            item["loan_id"] == writable_account["id"] and item["kind"] == "CALL"
            and item["notes"] == "Follow up after collection call."
            for item in client.get("/api/followups?period=all&status=ALL").json()
        )

        created_payment = client.post("/api/payments", json={
            "loan_id": writable_account["id"],
            "agent_id": agent_id,
            "amount": "1.25",
            "method": "Synthetic audit test",
        })
        assert created_payment.status_code == 201, created_payment.text
        assert any(
            payment["id"] == created_payment.json()["id"]
            for payment in client.get(
                f"/api/payments?loan_id={writable_account['id']}"
            ).json()
        )
        assert any(
            entry["event_type"] == "PAYMENT_RECORDED"
            for entry in client.get(
                f"/api/audit-logs?loan_id={writable_account['id']}"
            ).json()
        )

        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
