from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base


class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    role = Column(String(80), nullable=False, default="Collections Agent")
    active = Column(Boolean, nullable=False, default=True)
    calls = relationship("CallLog", back_populates="agent")
    payments = relationship("Payment", back_populates="agent")
    followups = relationship("FollowUp", back_populates="agent")


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(160), nullable=False, index=True)
    email = Column(String(255), nullable=False)
    phone = Column(String(40), nullable=False)
    city = Column(String(100), nullable=False)
    state = Column(String(50), nullable=False)
    preferred_contact = Column(String(30), nullable=False, default="Phone")
    contact_restricted = Column(Boolean, nullable=False, default=False)
    loans = relationship("Loan", back_populates="customer", cascade="all, delete-orphan")


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = (
        CheckConstraint("principal_amount > 0", name="ck_loan_principal_positive"),
        CheckConstraint("outstanding_amount >= 0", name="ck_loan_outstanding_nonnegative"),
        CheckConstraint("days_past_due >= 0", name="ck_loan_dpd_nonnegative"),
    )
    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(String(40), unique=True, nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    product = Column(String(80), nullable=False)
    principal_amount = Column(Float, nullable=False)
    outstanding_amount = Column(Float, nullable=False)
    days_past_due = Column(Integer, nullable=False, default=0)
    status = Column(String(30), nullable=False, default="CURRENT", index=True)
    is_disputed = Column(Boolean, nullable=False, default=False)
    opened_at = Column(Date, nullable=False)
    customer = relationship("Customer", back_populates="loans")
    agent = relationship("Agent")
    calls = relationship("CallLog", back_populates="loan", cascade="all, delete-orphan", order_by="CallLog.contacted_at.desc()")
    payments = relationship("Payment", back_populates="loan", cascade="all, delete-orphan", order_by="Payment.paid_at.desc()")
    followups = relationship("FollowUp", back_populates="loan", cascade="all, delete-orphan", order_by="FollowUp.due_at")
    promises = relationship("PaymentPromise", back_populates="loan", cascade="all, delete-orphan", order_by="PaymentPromise.due_at")


class CallLog(Base):
    __tablename__ = "call_logs"
    __table_args__ = (
        CheckConstraint("outcome IN ('PAID', 'PROMISED_TO_PAY', 'NOT_REACHABLE', 'DISPUTE')", name="ck_call_outcome"),
    )
    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    outcome = Column(String(30), nullable=False)
    notes = Column(Text, nullable=False)
    promise_date = Column(Date, nullable=True)
    contacted_at = Column(DateTime, nullable=False, index=True)
    loan = relationship("Loan", back_populates="calls")
    agent = relationship("Agent", back_populates="calls")
    promise = relationship("PaymentPromise", back_populates="call", uselist=False, cascade="all, delete-orphan")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_payment_amount_positive"),)
    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    amount = Column(Float, nullable=False)
    method = Column(String(50), nullable=False, default="Bank transfer")
    paid_at = Column(DateTime, nullable=False, index=True)
    loan = relationship("Loan", back_populates="payments")
    agent = relationship("Agent", back_populates="payments")
    satisfied_promises = relationship("PaymentPromise", back_populates="satisfied_by_payment")


class PaymentPromise(Base):
    __tablename__ = "payment_promises"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'KEPT', 'MISSED')", name="ck_payment_promise_status"),
    )
    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True)
    call_id = Column(Integer, ForeignKey("call_logs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True, index=True)
    due_at = Column(DateTime, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    created_at = Column(DateTime, nullable=False)
    loan = relationship("Loan", back_populates="promises")
    call = relationship("CallLog", back_populates="promise")
    agent = relationship("Agent")
    satisfied_by_payment = relationship("Payment", back_populates="satisfied_promises")
    followup = relationship("FollowUp", back_populates="promise", uselist=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(60), nullable=False, index=True)
    entity_type = Column(String(40), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True)
    details = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, index=True)


class FollowUp(Base):
    __tablename__ = "followups"
    __table_args__ = (
        CheckConstraint("status IN ('OPEN', 'COMPLETED', 'CANCELLED', 'MISSED')", name="ck_followup_status"),
    )
    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    promise_id = Column(Integer, ForeignKey("payment_promises.id", ondelete="SET NULL"), nullable=True, unique=True, index=True)
    due_at = Column(DateTime, nullable=False, index=True)
    kind = Column(String(40), nullable=False, default="CALL")
    notes = Column(Text, nullable=False, default="")
    status = Column(String(20), nullable=False, default="OPEN", index=True)
    created_at = Column(DateTime, nullable=False)
    loan = relationship("Loan", back_populates="followups")
    agent = relationship("Agent", back_populates="followups")
    promise = relationship("PaymentPromise", back_populates="followup")
