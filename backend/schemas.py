from datetime import date, datetime
from enum import Enum

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CallOutcome(str, Enum):
    PAID = "PAID"
    PROMISED_TO_PAY = "PROMISED_TO_PAY"
    NOT_REACHABLE = "NOT_REACHABLE"
    DISPUTE = "DISPUTE"


class CallCreate(BaseModel):
    loan_id: int = Field(gt=0)
    agent_id: int = Field(gt=0)
    outcome: CallOutcome
    notes: str = Field(min_length=2, max_length=4000)
    promise_date: date | None = None
    payment_amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    follow_up_at: datetime | None = None
    human_review_approved: bool = False

    @field_validator("notes", mode="before")
    @classmethod
    def validate_call_notes(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Call notes cannot be blank.")
        return value.strip()

    @model_validator(mode="after")
    def validate_outcome_fields(self):
        if self.outcome == CallOutcome.PROMISED_TO_PAY and self.promise_date is None:
            raise ValueError("A promise date is required for promised payments.")
        if self.outcome == CallOutcome.PROMISED_TO_PAY and self.promise_date < date.today():
            raise ValueError("A promised payment date cannot be in the past.")
        if self.promise_date is not None and self.outcome != CallOutcome.PROMISED_TO_PAY:
            raise ValueError("A promise date is only valid for a promised payment.")
        if self.outcome == CallOutcome.PAID and self.payment_amount is None:
            raise ValueError("A payment amount is required for a paid outcome.")
        if self.payment_amount is not None and self.outcome != CallOutcome.PAID:
            raise ValueError("A payment amount is only valid for a paid outcome.")
        if self.follow_up_at is not None and self.outcome != CallOutcome.NOT_REACHABLE:
            raise ValueError("A call follow-up can only be scheduled when the borrower was not reached.")
        return self


class PaymentCreate(BaseModel):
    loan_id: int = Field(gt=0)
    agent_id: int | None = Field(default=None, gt=0)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    method: str = Field(default="Bank transfer", min_length=2, max_length=50)
    paid_at: datetime | None = None

    @field_validator("method", mode="before")
    @classmethod
    def validate_payment_method(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Payment method cannot be blank.")
        return value.strip()


class AccountUpdate(BaseModel):
    days_past_due: int | None = Field(default=None, ge=0, le=36500)
    is_disputed: bool | None = None
    contact_restricted: bool | None = None

    @model_validator(mode="after")
    def validate_changes(self):
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("Provide at least one account field to update.")
        return self


class FollowUpCreate(BaseModel):
    loan_id: int = Field(gt=0)
    agent_id: int = Field(gt=0)
    due_at: datetime
    kind: str = Field(default="CALL", min_length=2, max_length=40)
    notes: str = Field(default="", max_length=2000)

    @field_validator("kind", mode="before")
    @classmethod
    def validate_followup_kind(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Follow-up type cannot be blank.")
        return value.strip()


class FollowUpUpdate(BaseModel):
    status: str

    @model_validator(mode="after")
    def validate_status(self):
        if self.status not in {"OPEN", "COMPLETED", "CANCELLED", "MISSED"}:
            raise ValueError("Status must be OPEN, COMPLETED, CANCELLED, or MISSED.")
        return self


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    role: str
    active: bool
