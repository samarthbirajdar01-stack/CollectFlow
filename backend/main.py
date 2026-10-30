import csv
import io
import json
import logging
import os
from calendar import month_abbr
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from database import Base, engine, get_db, migrate_followup_statuses
from models import Agent, AuditLog, CallLog, Customer, FollowUp, Loan, Payment, PaymentPromise
from schemas import AccountUpdate, AgentOut, CallCreate, FollowUpCreate, FollowUpUpdate, PaymentCreate
from seed import seed_database

logger = logging.getLogger("collectflow.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_followup_statuses()
    seed_database()
    _backfill_promises()
    _backfill_audit_logs()
    yield


app = FastAPI(
    title="CollectFlow API",
    version="1.0.0",
    description="Collections agent workbench API",
    lifespan=lifespan,
)
origins = [origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(IntegrityError)
async def handle_integrity_error(_request: Request, error: IntegrityError):
    logger.warning("Database constraint rejected a request: %s", error.orig)
    return JSONResponse(
        status_code=409,
        content={"detail": "The requested change conflicts with the current account data."},
    )


@app.exception_handler(SQLAlchemyError)
async def handle_database_error(_request: Request, error: SQLAlchemyError):
    logger.exception("CollectFlow database operation failed")
    return JSONResponse(
        status_code=500,
        content={"detail": "A database error prevented the request from completing."},
    )


def _account_query(db: Session):
    return db.query(Loan).options(
        joinedload(Loan.customer),
        joinedload(Loan.calls),
        joinedload(Loan.agent),
    )


def _latest_call(loan: Loan):
    return max(loan.calls, key=lambda call: call.contacted_at, default=None)


def _priority(loan: Loan, max_balance: float, max_dpd: int):
    amount_score = loan.outstanding_amount / max_balance if max_balance else 0
    days_score = loan.days_past_due / max_dpd if max_dpd else 0
    outcome_scores = {"NOT_REACHABLE": 1.0, "PROMISED_TO_PAY": 0.65, "DISPUTE": 0.0, "PAID": 0.0}
    contact_score = (
        sum(outcome_scores.get(call.outcome, 0.5) for call in loan.calls) / len(loan.calls)
        if loan.calls else 0.5
    )
    score = round((amount_score * 40) + (days_score * 35) + (contact_score * 25), 1)
    review_reasons = []
    if loan.is_disputed:
        review_reasons.append("Account is in dispute")
    if loan.customer.contact_restricted:
        review_reasons.append("Customer has a contact restriction")
    explanation = (
        f"Balance {amount_score * 40:.0f}/40 · "
        f"Days overdue {days_score * 35:.0f}/35 · "
        f"Contact history {contact_score * 25:.0f}/25"
    )
    return score, explanation, review_reasons


def _is_priority_eligible(loan: Loan):
    return (
        loan.outstanding_amount > 0
        and not loan.is_disputed
        and not loan.customer.contact_restricted
    )


def _serialize_account(loan: Loan, max_balance: float, max_dpd: int):
    score, explanation, review_reasons = _priority(loan, max_balance, max_dpd)
    latest = _latest_call(loan)
    return {
        "id": loan.id,
        "loan_id": loan.loan_id,
        "customer_id": loan.customer_id,
        "customer_name": loan.customer.full_name,
        "email": loan.customer.email,
        "phone": loan.customer.phone,
        "city": loan.customer.city,
        "product": loan.product,
        "principal_amount": loan.principal_amount,
        "outstanding_amount": round(loan.outstanding_amount, 2),
        "days_past_due": loan.days_past_due,
        "status": loan.status,
        "agent_id": loan.agent_id,
        "agent_name": loan.agent.name,
        "is_disputed": loan.is_disputed,
        "contact_restricted": loan.customer.contact_restricted,
        "requires_review": bool(review_reasons),
        "priority_eligible": _is_priority_eligible(loan),
        "review_reasons": review_reasons,
        "priority_score": score,
        "priority_explanation": explanation,
        "last_contact": latest.contacted_at if latest else None,
        "last_outcome": latest.outcome if latest else None,
    }


def _serialize_promise(promise: PaymentPromise):
    return {
        "id": promise.id,
        "loan_id": promise.loan_id,
        "loan_number": promise.loan.loan_id,
        "customer_id": promise.loan.customer_id,
        "customer_name": promise.loan.customer.full_name,
        "agent_id": promise.agent_id,
        "agent_name": promise.agent.name,
        "call_id": promise.call_id,
        "payment_id": promise.payment_id,
        "due_at": promise.due_at,
        "status": promise.status,
        "created_at": promise.created_at,
    }


def _all_accounts(db: Session):
    accounts = _account_query(db).all()
    eligible = [loan for loan in accounts if _is_priority_eligible(loan)]
    max_balance = max((loan.outstanding_amount for loan in eligible), default=0)
    max_dpd = max((loan.days_past_due for loan in eligible), default=0)
    return accounts, max_balance, max_dpd


def _serialize_followup(followup: FollowUp):
    loan = followup.loan
    return {
        "id": followup.id,
        "loan_id": loan.id,
        "loan_number": loan.loan_id,
        "customer_id": loan.customer_id,
        "customer_name": loan.customer.full_name,
        "outstanding_amount": loan.outstanding_amount,
        "due_at": followup.due_at,
        "kind": followup.kind,
        "notes": followup.notes,
        "status": followup.status,
        "promise_status": followup.promise.status if followup.promise else None,
        "promise_id": followup.promise_id,
        "agent_id": followup.agent_id,
        "agent_name": followup.agent.name,
    }


def _serialize_payment(payment: Payment):
    return {
        "id": payment.id,
        "loan_id": payment.loan.id,
        "loan_number": payment.loan.loan_id,
        "customer_id": payment.loan.customer_id,
        "customer_name": payment.loan.customer.full_name,
        "agent_name": payment.agent.name if payment.agent else "System",
        "amount": payment.amount,
        "method": payment.method,
        "paid_at": payment.paid_at,
    }


def _audit(
    db: Session,
    event_type: str,
    entity_type: str,
    entity_id: int,
    loan: Loan | None = None,
    agent_id: int | None = None,
    details: dict | None = None,
    created_at: datetime | None = None,
):
    db.add(AuditLog(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        loan_id=loan.id if loan else None,
        customer_id=loan.customer_id if loan else None,
        agent_id=agent_id,
        details=json.dumps(details or {}, sort_keys=True, default=str),
        created_at=created_at or datetime.now().replace(microsecond=0),
    ))


def _refresh_commitments(db: Session, now: datetime | None = None):
    current_time = now or datetime.now().replace(tzinfo=None)
    overdue = db.query(PaymentPromise).filter(
        PaymentPromise.status == "PENDING",
        PaymentPromise.due_at < current_time,
    ).all()
    for promise in overdue:
        promise.status = "MISSED"
        if promise.followup and promise.followup.status == "OPEN":
            promise.followup.status = "MISSED"
        _audit(
            db, "PROMISE_MISSED", "promise", promise.id,
            loan=promise.loan, agent_id=promise.agent_id,
            details={"due_at": promise.due_at.isoformat()},
        )
    if overdue:
        db.commit()
    return len(overdue)


def _backfill_promises():
    from database import SessionLocal

    db = SessionLocal()
    try:
        calls = db.query(CallLog).filter(
            CallLog.outcome == "PROMISED_TO_PAY",
            CallLog.promise_date.is_not(None),
            ~CallLog.promise.has(),
        ).all()
        for call in calls:
            due_at = datetime.combine(call.promise_date, time.max).replace(microsecond=0)
            matching_payment = db.query(Payment).filter(
                Payment.loan_id == call.loan_id,
                Payment.paid_at >= call.contacted_at,
                Payment.paid_at <= due_at,
            ).order_by(Payment.paid_at).first()
            promise = PaymentPromise(
                loan_id=call.loan_id,
                call_id=call.id,
                agent_id=call.agent_id,
                payment_id=matching_payment.id if matching_payment else None,
                due_at=due_at,
                status="KEPT" if matching_payment else ("MISSED" if due_at < datetime.now() else "PENDING"),
                created_at=call.contacted_at,
            )
            db.add(promise)
            db.flush()
            followup = db.query(FollowUp).filter(
                FollowUp.loan_id == call.loan_id,
                FollowUp.kind == "PROMISE_CHECK",
                FollowUp.due_at >= datetime.combine(call.promise_date, time.min),
                FollowUp.due_at < datetime.combine(call.promise_date + timedelta(days=1), time.min),
                FollowUp.promise_id.is_(None),
            ).first()
            if followup is None:
                followup = FollowUp(
                    loan_id=call.loan_id,
                    agent_id=call.agent_id,
                    due_at=due_at,
                    kind="PROMISE_CHECK",
                    notes="Check in on promised payment.",
                    status="OPEN",
                    created_at=call.contacted_at,
                )
                db.add(followup)
            followup.promise = promise
            followup.status = (
                "COMPLETED" if promise.status == "KEPT"
                else "MISSED" if promise.status == "MISSED"
                else "OPEN"
            )
        db.commit()
    finally:
        db.close()


def _backfill_audit_logs():
    from database import SessionLocal

    db = SessionLocal()
    try:
        existing_records = {
            (entry.entity_type, entry.entity_id)
            for entry in db.query(AuditLog.entity_type, AuditLog.entity_id).filter(
                AuditLog.entity_type.in_(["loan", "call", "payment", "promise"])
            ).all()
        }
        for loan in db.query(Loan).options(joinedload(Loan.customer)).all():
            if ("loan", loan.id) not in existing_records:
                _audit(
                    db, "ACCOUNT_IMPORTED", "loan", loan.id, loan=loan,
                    agent_id=loan.agent_id,
                    details={
                        "principal_amount": round(loan.principal_amount, 2),
                        "outstanding_amount": round(loan.outstanding_amount, 2),
                        "days_past_due": loan.days_past_due,
                        "status": loan.status,
                        "is_disputed": loan.is_disputed,
                        "contact_restricted": loan.customer.contact_restricted,
                    },
                    created_at=datetime.combine(loan.opened_at, time.min),
                )
        for call in db.query(CallLog).all():
            if ("call", call.id) not in existing_records:
                _audit(
                    db, "CALL_IMPORTED", "call", call.id, loan=call.loan,
                    agent_id=call.agent_id,
                    details={
                        "outcome": call.outcome,
                        "notes": call.notes,
                        "contacted_at": call.contacted_at.isoformat(),
                        "promise_date": call.promise_date.isoformat() if call.promise_date else None,
                    },
                    created_at=call.contacted_at,
                )
        for payment in db.query(Payment).all():
            if ("payment", payment.id) not in existing_records:
                _audit(
                    db, "PAYMENT_IMPORTED", "payment", payment.id, loan=payment.loan,
                    agent_id=payment.agent_id,
                    details={
                        "amount": round(payment.amount, 2),
                        "method": payment.method,
                        "paid_at": payment.paid_at.isoformat(),
                    },
                    created_at=payment.paid_at,
                )
        for promise in db.query(PaymentPromise).all():
            if ("promise", promise.id) not in existing_records:
                _audit(
                    db, "PROMISE_IMPORTED", "promise", promise.id, loan=promise.loan,
                    agent_id=promise.agent_id,
                    details={
                        "call_id": promise.call_id,
                        "due_at": promise.due_at.isoformat(),
                        "status": promise.status,
                        "payment_id": promise.payment_id,
                    },
                    created_at=promise.created_at,
                )
        db.commit()
    finally:
        db.close()


def _record_payment(db: Session, loan: Loan, amount: Decimal, method: str, agent_id: int | None, paid_at: datetime):
    amount = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    outstanding = Decimal(str(loan.outstanding_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise HTTPException(status_code=422, detail="Payment amount must be greater than zero.")
    if amount > outstanding:
        raise HTTPException(status_code=422, detail="Payment cannot exceed the outstanding balance.")
    if paid_at.tzinfo is not None:
        paid_at = paid_at.astimezone().replace(tzinfo=None)
    if paid_at > datetime.now():
        raise HTTPException(status_code=422, detail="Payment date cannot be in the future.")
    previous_balance = outstanding
    result = db.execute(
        update(Loan)
        .where(Loan.id == loan.id, Loan.outstanding_amount >= float(amount))
        .values(outstanding_amount=Loan.outstanding_amount - float(amount))
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=422, detail="Payment exceeds the current outstanding balance.")
    db.refresh(loan)
    loan.outstanding_amount = round(loan.outstanding_amount, 2)
    payment = Payment(loan=loan, agent_id=agent_id, amount=float(amount), method=method, paid_at=paid_at)
    if loan.outstanding_amount == 0:
        loan.status = "PAID"
        loan.days_past_due = 0
    elif loan.status == "PAID":
        loan.status = "OVERDUE" if loan.days_past_due else "CURRENT"
    db.add(payment)
    db.flush()
    commitment = db.query(PaymentPromise).filter(
        PaymentPromise.loan_id == loan.id,
        PaymentPromise.status == "PENDING",
        PaymentPromise.created_at <= paid_at,
        PaymentPromise.due_at >= paid_at,
    ).order_by(PaymentPromise.created_at).first()
    if commitment:
        commitment.status = "KEPT"
        commitment.payment_id = payment.id
        if commitment.followup and commitment.followup.status == "OPEN":
            commitment.followup.status = "COMPLETED"
        _audit(
            db, "PROMISE_KEPT", "promise", commitment.id,
            loan=loan, agent_id=agent_id,
            details={"payment_id": payment.id, "amount": str(amount)},
        )
    _audit(
        db, "PAYMENT_RECORDED", "payment", payment.id,
        loan=loan, agent_id=agent_id,
        details={
            "amount": str(amount),
            "balance_before": str(previous_balance),
            "balance_after": str(Decimal(str(loan.outstanding_amount)).quantize(Decimal("0.01"))),
            "status_after": loan.status,
            "method": method,
            "paid_at": paid_at.isoformat(),
        },
    )
    return payment


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "CollectFlow API"}


@app.get("/api/agents", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db)):
    return db.query(Agent).filter(Agent.active.is_(True)).order_by(Agent.name).all()


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    _refresh_commitments(db)
    today = date.today()
    start_of_month = datetime.combine(today.replace(day=1), time.min)
    loans = db.query(Loan).all()
    payments = db.query(Payment).all()
    active_loans = [loan for loan in loans if loan.outstanding_amount > 0]
    month_recovered = sum(payment.amount for payment in payments if payment.paid_at >= start_of_month)
    total_recovered = sum(payment.amount for payment in payments)
    total_principal = sum(loan.principal_amount for loan in loans)
    open_followups = db.query(FollowUp).filter(
        FollowUp.status == "OPEN",
        FollowUp.due_at >= datetime.combine(today, time.min),
        FollowUp.due_at < datetime.combine(today + timedelta(days=1), time.min),
    ).count()
    upcoming_followups = db.query(FollowUp).filter(
        FollowUp.status == "OPEN",
        FollowUp.due_at >= datetime.combine(today + timedelta(days=1), time.min),
    ).count()
    overdue_followups = db.query(FollowUp).filter(
        FollowUp.status == "OPEN",
        FollowUp.due_at < datetime.combine(today, time.min),
    ).count()

    trend = []
    for offset in range(5, -1, -1):
        first_of_month = (today.replace(day=1) - timedelta(days=offset * 28)).replace(day=1)
        next_month = (first_of_month.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_total = sum(
            payment.amount for payment in payments
            if first_of_month <= payment.paid_at.date() < next_month
        )
        trend.append({"month": month_abbr[first_of_month.month], "recovered": round(month_total, 2)})

    agents = db.query(Agent).filter(Agent.active.is_(True)).order_by(Agent.name).all()
    performance = []
    for agent in agents:
        agent_recovered = sum(payment.amount for payment in payments if payment.agent_id == agent.id)
        performance.append({"name": agent.name.split()[0], "recovered": round(agent_recovered, 2)})

    recent_calls = db.query(CallLog).options(
        joinedload(CallLog.loan).joinedload(Loan.customer), joinedload(CallLog.agent)
    ).order_by(CallLog.contacted_at.desc()).limit(6).all()
    recent_payments = db.query(Payment).options(
        joinedload(Payment.loan).joinedload(Loan.customer), joinedload(Payment.agent)
    ).order_by(Payment.paid_at.desc()).limit(6).all()
    recent_activities = [
        {
            "id": f"call-{call.id}",
            "type": "call",
            "customer_name": call.loan.customer.full_name,
            "description": call.outcome.replace("_", " ").title(),
            "agent_name": call.agent.name,
            "amount": None,
            "created_at": call.contacted_at,
        }
        for call in recent_calls
    ] + [
        {
            "id": f"payment-{payment.id}",
            "type": "payment",
            "customer_name": payment.loan.customer.full_name,
            "description": f"{payment.method} payment",
            "agent_name": payment.agent.name if payment.agent else "System",
            "amount": payment.amount,
            "created_at": payment.paid_at,
        }
        for payment in recent_payments
    ]
    recent_activities.sort(key=lambda activity: activity["created_at"], reverse=True)

    return {
        "metrics": {
            "assigned_accounts": len(loans),
            "total_outstanding": round(sum(loan.outstanding_amount for loan in loans), 2),
            "recovered_this_month": round(month_recovered, 2),
            "recovered_total": round(total_recovered, 2),
            "recovery_rate": round(total_recovered / total_principal * 100, 1) if total_principal else 0,
            "todays_followups": open_followups,
            "upcoming_followups": upcoming_followups,
            "overdue_followups": overdue_followups,
            "overdue_accounts": sum(1 for loan in active_loans if loan.days_past_due > 0 and not loan.is_disputed),
            "accounts_needing_review": sum(
                1 for loan in active_loans if loan.is_disputed or loan.customer.contact_restricted
            ),
        },
        "recovery_trend": trend,
        "agent_performance": performance,
        "recent_activities": recent_activities[:8],
    }


@app.get("/api/accounts")
def list_accounts(
    search: str = Query(default="", max_length=120),
    status: str = Query(default="ALL", pattern="^(ALL|CURRENT|OVERDUE|PAID|DISPUTED)$"),
    review: bool | None = None,
    db: Session = Depends(get_db),
):
    _refresh_commitments(db)
    accounts, max_balance, max_dpd = _all_accounts(db)
    results = []
    for loan in accounts:
        row = _serialize_account(loan, max_balance, max_dpd)
        if search and search.casefold() not in " ".join(
            [row["customer_name"], row["loan_id"], row["phone"], row["email"]]
        ).casefold():
            continue
        if status != "ALL" and loan.status != status:
            continue
        if review is not None and row["requires_review"] != review:
            continue
        results.append(row)
    results.sort(key=lambda row: (
        row["priority_eligible"],
        row["priority_score"],
        row["outstanding_amount"],
    ), reverse=True)
    return results


@app.patch("/api/accounts/{loan_id}")
def update_account(loan_id: int, payload: AccountUpdate, db: Session = Depends(get_db)):
    loan = db.query(Loan).options(joinedload(Loan.customer)).filter(Loan.id == loan_id).first()
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan account not found.")

    changes = payload.model_dump(exclude_none=True)
    before = {
        "outstanding_amount": round(loan.outstanding_amount, 2),
        "days_past_due": loan.days_past_due,
        "is_disputed": loan.is_disputed,
        "contact_restricted": loan.customer.contact_restricted,
        "status": loan.status,
    }
    if "days_past_due" in changes:
        loan.days_past_due = changes["days_past_due"]
    if "is_disputed" in changes:
        loan.is_disputed = changes["is_disputed"]
    if "contact_restricted" in changes:
        loan.customer.contact_restricted = changes["contact_restricted"]

    if loan.outstanding_amount == 0:
        loan.status = "PAID"
        loan.days_past_due = 0
    elif loan.is_disputed:
        loan.status = "DISPUTED"
    else:
        loan.status = "OVERDUE" if loan.days_past_due else "CURRENT"

    after = {
        "outstanding_amount": round(loan.outstanding_amount, 2),
        "days_past_due": loan.days_past_due,
        "is_disputed": loan.is_disputed,
        "contact_restricted": loan.customer.contact_restricted,
        "status": loan.status,
    }
    if before != after:
        _audit(
            db, "ACCOUNT_UPDATED", "loan", loan.id, loan=loan,
            details={"before": before, "after": after},
        )
    db.commit()
    accounts, max_balance, max_dpd = _all_accounts(db)
    updated = next(account for account in accounts if account.id == loan.id)
    return _serialize_account(updated, max_balance, max_dpd)


@app.get("/api/customers")
def list_customers(
    search: str = Query(default="", max_length=120),
    db: Session = Depends(get_db),
):
    customers = db.query(Customer).options(joinedload(Customer.loans)).order_by(Customer.full_name).all()
    output = []
    for customer in customers:
        if search and search.casefold() not in f"{customer.full_name} {customer.email} {customer.phone}".casefold():
            continue
        total_outstanding = sum(loan.outstanding_amount for loan in customer.loans)
        output.append({
            "id": customer.id,
            "full_name": customer.full_name,
            "email": customer.email,
            "phone": customer.phone,
            "city": customer.city,
            "state": customer.state,
            "preferred_contact": customer.preferred_contact,
            "contact_restricted": customer.contact_restricted,
            "loan_count": len(customer.loans),
            "total_outstanding": round(total_outstanding, 2),
            "loans": [{"id": loan.id, "loan_id": loan.loan_id, "status": loan.status, "outstanding_amount": loan.outstanding_amount} for loan in customer.loans],
        })
    return output


@app.get("/api/customers/{customer_id}")
def customer_detail(customer_id: int, db: Session = Depends(get_db)):
    customer = db.query(Customer).options(
        joinedload(Customer.loans).joinedload(Loan.calls).joinedload(CallLog.agent),
        joinedload(Customer.loans).joinedload(Loan.payments).joinedload(Payment.agent),
        joinedload(Customer.loans).joinedload(Loan.followups).joinedload(FollowUp.agent),
        joinedload(Customer.loans).joinedload(Loan.promises).joinedload(PaymentPromise.agent),
        joinedload(Customer.loans).joinedload(Loan.agent),
    ).filter(Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    loans = []
    for loan in customer.loans:
        loans.append({
            "id": loan.id,
            "loan_id": loan.loan_id,
            "product": loan.product,
            "principal_amount": loan.principal_amount,
            "outstanding_amount": loan.outstanding_amount,
            "days_past_due": loan.days_past_due,
            "status": loan.status,
            "is_disputed": loan.is_disputed,
            "agent_name": loan.agent.name,
            "calls": [{
                "id": call.id, "outcome": call.outcome, "notes": call.notes,
                "promise_date": call.promise_date, "contacted_at": call.contacted_at,
                "agent_name": call.agent.name,
            } for call in loan.calls],
            "payments": [{
                "id": payment.id, "amount": payment.amount, "method": payment.method,
                "paid_at": payment.paid_at, "agent_name": payment.agent.name if payment.agent else "System",
            } for payment in loan.payments],
            "followups": [{
                "id": followup.id, "due_at": followup.due_at, "kind": followup.kind,
                "notes": followup.notes, "status": followup.status,
                "agent_name": followup.agent.name,
            } for followup in loan.followups],
            "promises": [{
                "id": promise.id, "due_at": promise.due_at, "status": promise.status,
                "agent_name": promise.agent.name, "payment_id": promise.payment_id,
            } for promise in loan.promises],
        })
    return {
        "id": customer.id,
        "full_name": customer.full_name,
        "email": customer.email,
        "phone": customer.phone,
        "city": customer.city,
        "state": customer.state,
        "preferred_contact": customer.preferred_contact,
        "contact_restricted": customer.contact_restricted,
        "loans": loans,
    }


@app.post("/api/calls", status_code=201)
def create_call(payload: CallCreate, db: Session = Depends(get_db)):
    loan = db.query(Loan).options(joinedload(Loan.customer)).filter(Loan.id == payload.loan_id).first()
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan account not found.")
    agent = db.query(Agent).filter(Agent.id == payload.agent_id, Agent.active.is_(True)).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Active agent not found.")
    if loan.outstanding_amount <= 0:
        raise HTTPException(status_code=409, detail="This account is already paid.")
    if (loan.is_disputed or loan.customer.contact_restricted) and not payload.human_review_approved:
        raise HTTPException(
            status_code=409,
            detail="This account requires documented human review before outreach.",
        )
    if payload.outcome == "PAID" and payload.payment_amount > Decimal(str(loan.outstanding_amount)):
        raise HTTPException(status_code=422, detail="Payment cannot exceed the outstanding balance.")

    note = payload.notes.strip()
    if payload.human_review_approved and (loan.is_disputed or loan.customer.contact_restricted):
        note = f"[Human review approved] {note}"
    call = CallLog(
        loan_id=loan.id,
        agent_id=agent.id,
        outcome=payload.outcome.value,
        notes=note,
        promise_date=payload.promise_date,
        contacted_at=datetime.now().replace(microsecond=0),
    )
    db.add(call)
    db.flush()
    _audit(
        db, "CALL_RECORDED", "call", call.id,
        loan=loan, agent_id=agent.id,
        details={
            "outcome": call.outcome,
            "notes": call.notes,
            "contacted_at": call.contacted_at.isoformat(),
            "promise_date": call.promise_date.isoformat() if call.promise_date else None,
        },
    )
    if payload.outcome == "PAID":
        _record_payment(db, loan, payload.payment_amount, "Collection call", agent.id, call.contacted_at)
    elif payload.outcome == "DISPUTE":
        was_disputed = loan.is_disputed
        was_restricted = loan.customer.contact_restricted
        loan.is_disputed = True
        loan.status = "DISPUTED"
        loan.customer.contact_restricted = True
        if not was_disputed or not was_restricted:
            _audit(
                db, "ACCOUNT_REVIEW_REQUIRED", "loan", loan.id,
                loan=loan, agent_id=agent.id,
                details={"is_disputed": True, "contact_restricted": True},
            )
    elif payload.outcome == "PROMISED_TO_PAY":
        due_at = datetime.combine(payload.promise_date, time.max).replace(microsecond=0)
        promise = PaymentPromise(
            loan_id=loan.id,
            call_id=call.id,
            agent_id=agent.id,
            due_at=due_at,
            status="PENDING",
            created_at=call.contacted_at,
        )
        db.add(promise)
        db.flush()
        followup = FollowUp(
            loan_id=loan.id, agent_id=agent.id, due_at=due_at,
            kind="PROMISE_CHECK", notes="Follow up on promised payment.",
            status="OPEN", promise=promise, created_at=call.contacted_at,
        )
        db.add(followup)
        _audit(
            db, "PROMISE_CREATED", "promise", promise.id,
            loan=loan, agent_id=agent.id,
            details={"call_id": call.id, "due_at": due_at.isoformat()},
        )
    elif payload.follow_up_at:
        followup = FollowUp(
            loan_id=loan.id, agent_id=agent.id, due_at=payload.follow_up_at,
            kind="CALL", notes="Follow up after collection call.",
            status="OPEN", created_at=call.contacted_at,
        )
        db.add(followup)
        db.flush()
        _audit(
            db, "FOLLOWUP_CREATED", "followup", followup.id,
            loan=loan, agent_id=agent.id,
            details={"due_at": followup.due_at.isoformat(), "kind": followup.kind},
        )
    db.commit()
    db.refresh(call)
    return {
        "id": call.id,
        "loan_id": call.loan_id,
        "outcome": call.outcome,
        "notes": call.notes,
        "promise_date": call.promise_date,
        "contacted_at": call.contacted_at,
        "payment_amount": payload.payment_amount if payload.outcome == "PAID" else None,
    }


@app.get("/api/calls")
def list_calls(
    loan_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(CallLog).options(joinedload(CallLog.agent), joinedload(CallLog.loan).joinedload(Loan.customer))
    if loan_id is not None:
        query = query.filter(CallLog.loan_id == loan_id)
    return [{
        "id": call.id,
        "loan_id": call.loan_id,
        "loan_number": call.loan.loan_id,
        "customer_name": call.loan.customer.full_name,
        "agent_name": call.agent.name,
        "outcome": call.outcome,
        "notes": call.notes,
        "promise_date": call.promise_date,
        "contacted_at": call.contacted_at,
    } for call in query.order_by(CallLog.contacted_at.desc()).limit(limit).all()]


@app.get("/api/followups")
def list_followups(
    period: str = Query(default="all", pattern="^(all|today|upcoming|overdue)$"),
    status: str = Query(default="OPEN", pattern="^(ALL|OPEN|COMPLETED|CANCELLED|MISSED)$"),
    db: Session = Depends(get_db),
):
    _refresh_commitments(db)
    today = date.today()
    start_today = datetime.combine(today, time.min)
    tomorrow = datetime.combine(today + timedelta(days=1), time.min)
    query = db.query(FollowUp).options(
        joinedload(FollowUp.loan).joinedload(Loan.customer),
        joinedload(FollowUp.agent),
        joinedload(FollowUp.promise),
    )
    if status != "ALL":
        query = query.filter(FollowUp.status == status)
    if period == "today":
        query = query.filter(FollowUp.due_at >= start_today, FollowUp.due_at < tomorrow)
    elif period == "upcoming":
        query = query.filter(FollowUp.due_at >= tomorrow)
    elif period == "overdue":
        query = query.filter(FollowUp.due_at < start_today, FollowUp.status == "OPEN")
    followups = query.order_by(FollowUp.due_at).all()
    return [_serialize_followup(followup) for followup in followups]


@app.post("/api/followups", status_code=201)
def create_followup(payload: FollowUpCreate, db: Session = Depends(get_db)):
    loan = db.query(Loan).filter(Loan.id == payload.loan_id).first()
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan account not found.")
    agent = db.query(Agent).filter(Agent.id == payload.agent_id, Agent.active.is_(True)).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Active agent not found.")
    followup = FollowUp(
        loan_id=loan.id, agent_id=agent.id, due_at=payload.due_at,
        kind=payload.kind, notes=payload.notes.strip(), status="OPEN",
        created_at=datetime.now().replace(microsecond=0),
    )
    db.add(followup)
    db.flush()
    _audit(
        db, "FOLLOWUP_CREATED", "followup", followup.id,
        loan=loan, agent_id=agent.id,
        details={"due_at": followup.due_at.isoformat(), "kind": followup.kind},
    )
    db.commit()
    db.refresh(followup)
    return _serialize_followup(followup)


@app.patch("/api/followups/{followup_id}")
def update_followup(followup_id: int, payload: FollowUpUpdate, db: Session = Depends(get_db)):
    followup = db.query(FollowUp).filter(FollowUp.id == followup_id).first()
    if followup is None:
        raise HTTPException(status_code=404, detail="Follow-up not found.")
    previous_status = followup.status
    followup.status = payload.status
    if previous_status != followup.status:
        _audit(
            db, "FOLLOWUP_STATUS_CHANGED", "followup", followup.id,
            loan=followup.loan, agent_id=followup.agent_id,
            details={"before": previous_status, "after": followup.status},
        )
    db.commit()
    return {"id": followup.id, "status": followup.status}


@app.get("/api/payments")
def list_payments(
    loan_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(Payment).options(
        joinedload(Payment.loan).joinedload(Loan.customer),
        joinedload(Payment.agent),
    )
    if loan_id is not None:
        query = query.filter(Payment.loan_id == loan_id)
    payments = query.order_by(Payment.paid_at.desc()).limit(limit).all()
    return [_serialize_payment(payment) for payment in payments]


@app.post("/api/payments", status_code=201)
def create_payment(payload: PaymentCreate, db: Session = Depends(get_db)):
    loan = db.query(Loan).filter(Loan.id == payload.loan_id).first()
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan account not found.")
    agent = None
    if payload.agent_id is not None:
        agent = db.query(Agent).filter(Agent.id == payload.agent_id, Agent.active.is_(True)).first()
        if agent is None:
            raise HTTPException(status_code=404, detail="Active agent not found.")
    payment = _record_payment(
        db, loan, payload.amount, payload.method, agent.id if agent else None,
        payload.paid_at or datetime.now().replace(microsecond=0),
    )
    _refresh_commitments(db)
    db.commit()
    db.refresh(payment)
    return _serialize_payment(payment)


@app.get("/api/promises")
def list_promises(
    status: str = Query(default="ALL", pattern="^(ALL|PENDING|KEPT|MISSED)$"),
    loan_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _refresh_commitments(db)
    query = db.query(PaymentPromise).options(
        joinedload(PaymentPromise.loan).joinedload(Loan.customer),
        joinedload(PaymentPromise.agent),
    )
    if status != "ALL":
        query = query.filter(PaymentPromise.status == status)
    if loan_id is not None:
        query = query.filter(PaymentPromise.loan_id == loan_id)
    promises = query.order_by(PaymentPromise.due_at.desc()).limit(limit).all()
    return [_serialize_promise(promise) for promise in promises]


@app.get("/api/audit-logs")
def list_audit_logs(
    loan_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)
    if loan_id is not None:
        query = query.filter(AuditLog.loan_id == loan_id)
    logs = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all()
    return [{
        "id": entry.id,
        "event_type": entry.event_type,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "loan_id": entry.loan_id,
        "customer_id": entry.customer_id,
        "agent_id": entry.agent_id,
        "details": json.loads(entry.details),
        "created_at": entry.created_at,
    } for entry in logs]


@app.get("/api/analytics")
def analytics(db: Session = Depends(get_db)):
    data = dashboard(db)
    payments = db.query(Payment).all()
    calls = db.query(CallLog).all()
    promises = db.query(PaymentPromise).all()
    resolved_promises = [promise for promise in promises if promise.status != "PENDING"]
    kept_promises = sum(1 for promise in resolved_promises if promise.status == "KEPT")
    successful_calls = sum(1 for call in calls if call.outcome == "PAID")
    total_calls = len(calls)
    return {
        **data,
        "recovery_rate": data["metrics"]["recovery_rate"],
        "recovered_total": data["metrics"]["recovered_total"],
        "recovered_this_month": data["metrics"]["recovered_this_month"],
        "payment_success_rate": round(successful_calls / total_calls * 100, 1) if total_calls else 0,
        "promise_to_pay_conversion_rate": round(kept_promises / len(resolved_promises) * 100, 1) if resolved_promises else 0,
        "total_calls": total_calls,
        "total_payments": len(payments),
        "total_promises": len(promises),
        "pending_promises": sum(1 for promise in promises if promise.status == "PENDING"),
        "kept_promises": kept_promises,
        "missed_promises": sum(1 for promise in promises if promise.status == "MISSED"),
    }


@app.get("/api/reports/collections.csv")
def export_collections(db: Session = Depends(get_db)):
    accounts, max_balance, max_dpd = _all_accounts(db)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Customer", "Loan ID", "Product", "Outstanding Amount",
        "Days Past Due", "Priority Score", "Status", "Agent", "Last Contact",
        "Requires Human Review",
    ])
    for loan in accounts:
        row = _serialize_account(loan, max_balance, max_dpd)
        writer.writerow([
            row["customer_name"], row["loan_id"], loan.product, row["outstanding_amount"],
            row["days_past_due"], row["priority_score"], row["status"], row["agent_name"],
            row["last_contact"].isoformat() if row["last_contact"] else "",
            "Yes" if row["requires_review"] else "No",
        ])
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="collectflow-collections.csv"'},
    )
