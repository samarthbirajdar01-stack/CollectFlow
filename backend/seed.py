import argparse
import os
import random
from datetime import date, datetime, time, timedelta

from database import Base, SessionLocal, engine
from models import Agent, CallLog, Customer, FollowUp, Loan, Payment, PaymentPromise


FIRST_NAMES = [
    "Jordan", "Taylor", "Morgan", "Riley", "Casey", "Avery", "Quinn", "Parker",
    "Jamie", "Drew", "Cameron", "Reese", "Skyler", "Rowan", "Elliot", "Finley",
    "Harper", "Sage", "Dakota", "Emerson", "Blake", "Kendall", "Logan", "River",
]
LAST_NAMES = [
    "Bennett", "Foster", "Hayes", "Brooks", "Patel", "Carter", "Reed", "Morgan",
    "Kim", "Turner", "Perry", "Bailey", "Cooper", "Price", "Ward", "Flores",
]
CITIES = [("Austin", "TX"), ("Denver", "CO"), ("Raleigh", "NC"), ("Phoenix", "AZ"), ("Portland", "OR"), ("Nashville", "TN")]
PRODUCTS = ["Personal loan", "Auto loan", "Credit builder", "Small business"]
OUTCOMES = ["NOT_REACHABLE", "PROMISED_TO_PAY", "NOT_REACHABLE", "PAID", "NOT_REACHABLE", "DISPUTE"]


def seed_database(reset=False):
    if reset:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Agent).count():
            return False

        demo_email = os.getenv("DEMO_AGENT_EMAIL", "alex.morgan@collectflow.demo")
        agents = [
            Agent(name="Alex Morgan", email=demo_email, role="Senior Collections Agent"),
            Agent(name="Priya Shah", email="priya.shah@collectflow.demo"),
            Agent(name="Marcus Lee", email="marcus.lee@collectflow.demo"),
            Agent(name="Elena Rivera", email="elena.rivera@collectflow.demo"),
            Agent(name="Theo Brooks", email="theo.brooks@collectflow.demo"),
        ]
        db.add_all(agents)
        db.flush()
        rng = random.Random(72)
        loans = []
        for index in range(36):
            first = FIRST_NAMES[index % len(FIRST_NAMES)]
            last = LAST_NAMES[(index * 5 + 2) % len(LAST_NAMES)]
            city, state = CITIES[index % len(CITIES)]
            customer = Customer(
                full_name=f"{first} {last}",
                email=f"{first.lower()}.{last.lower()}.{index + 1}@example.com",
                phone=f"+1 (555) {200 + index:03d}-{1000 + index:04d}",
                city=city,
                state=state,
                preferred_contact="Email" if index % 5 == 0 else "Phone",
                contact_restricted=index in {8, 21},
            )
            db.add(customer)
            principal = float(rng.randrange(3500, 32000, 250))
            dpd = [0, 5, 12, 19, 28, 37, 46, 61, 75, 92][index % 10]
            disputed = index in {5, 21}
            loans.append(Loan(
                loan_id=f"LN-{2026}-{10001 + index}",
                customer=customer,
                agent=agents[index % len(agents)],
                product=PRODUCTS[index % len(PRODUCTS)],
                principal_amount=principal,
                outstanding_amount=principal,
                days_past_due=dpd,
                status="DISPUTED" if disputed else ("CURRENT" if dpd == 0 else "OVERDUE"),
                is_disputed=disputed,
                opened_at=date.today() - timedelta(days=180 + index * 11),
            ))
        db.add_all(loans)
        db.flush()

        now = datetime.now().replace(microsecond=0)
        for index, loan in enumerate(loans):
            if index % 8 != 0:
                payment_amount = loan.principal_amount if index % 3 == 1 else round(
                    min(loan.principal_amount * 0.12 + (index % 4) * 55, loan.principal_amount * 0.4), 2
                )
                days_ago = (index * 13) % 165
                db.add(Payment(
                    loan=loan,
                    agent=agents[index % len(agents)],
                    amount=payment_amount,
                    method=["Bank transfer", "Debit card", "ACH"][index % 3],
                    paid_at=now - timedelta(days=days_ago, hours=index % 10),
                ))
                loan.outstanding_amount = round(loan.principal_amount - payment_amount, 2)

            if index % 3 == 1:
                loan.status = "PAID"
                loan.outstanding_amount = 0
                loan.days_past_due = 0
            elif not loan.is_disputed:
                loan.status = "CURRENT" if loan.days_past_due == 0 else "OVERDUE"

        db.flush()
        for index in range(72):
            loan = loans[(index * 7 + index // 5) % len(loans)]
            outcome = OUTCOMES[(index * 5 + index // 6) % len(OUTCOMES)]
            if loan.is_disputed:
                outcome = "DISPUTE"
            contacted_at = now - timedelta(days=(index * 3) % 150, hours=index % 12)
            promise_date = contacted_at.date() + timedelta(days=2 + index % 9) if outcome == "PROMISED_TO_PAY" else None
            call = CallLog(
                loan=loan,
                agent=agents[index % len(agents)],
                outcome=outcome,
                notes=[
                    "Discussed account and agreed next steps.",
                    "Borrower requested a convenient callback time.",
                    "Reviewed payment options and account details.",
                    "Follow-up scheduled to revisit the balance.",
                ][index % 4],
                promise_date=promise_date,
                contacted_at=contacted_at,
            )
            db.add(call)
            db.flush()
            if outcome == "PROMISED_TO_PAY":
                due_at = datetime.combine(promise_date, time.max).replace(microsecond=0)
                matching_payment = db.query(Payment).filter(
                    Payment.loan_id == loan.id,
                    Payment.paid_at >= contacted_at,
                    Payment.paid_at <= due_at,
                ).order_by(Payment.paid_at).first()
                promise = PaymentPromise(
                    loan=loan,
                    call=call,
                    agent=agents[index % len(agents)],
                    payment_id=matching_payment.id if matching_payment else None,
                    due_at=due_at,
                    status="KEPT" if matching_payment else ("MISSED" if due_at < now else "PENDING"),
                    created_at=contacted_at,
                )
                db.add(promise)
                db.flush()
                db.add(FollowUp(
                    loan=loan,
                    agent=agents[index % len(agents)],
                    due_at=due_at,
                    kind="PROMISE_CHECK",
                    notes="Check in on promised payment.",
                    promise=promise,
                    status="COMPLETED" if promise.status == "KEPT" else (
                        "MISSED" if promise.status == "MISSED" else "OPEN"
                    ),
                    created_at=contacted_at,
                ))
            elif index % 7 == 0:
                due_date = now.date() + timedelta(days=(index % 5) - 2)
                db.add(FollowUp(
                    loan=loan,
                    agent=agents[index % len(agents)],
                    due_at=datetime.combine(due_date, time(hour=9 + index % 8)),
                    kind="CALL",
                    notes="Scheduled account follow-up.",
                    status="OPEN" if index % 3 else "COMPLETED",
                    created_at=contacted_at,
                ))

        db.commit()
        return True
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize CollectFlow with synthetic demo data.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop all existing tables and recreate the synthetic demo dataset.",
    )
    arguments = parser.parse_args()
    seeded = seed_database(reset=arguments.reset)
    if seeded:
        print("CollectFlow database initialized and synthetic demo data seeded.")
    else:
        print("CollectFlow already contains an agent; no data was changed. Use --reset to recreate the demo dataset.")
