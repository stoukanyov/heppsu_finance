"""Pydantic схеми за AI модула."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    model: str
    data: dict
    created_at: dt.datetime


class CfoQuestion(BaseModel):
    question: str | None = Field(default=None, max_length=1000)
    period_id: uuid.UUID | None = None


class CfoAnswer(BaseModel):
    summary: str
    explanation: str
    recommendations: list[str] = []
    risks: list[str] = []
    assumptions: list[str] = []
    confidence: str
    context: dict  # използваните финансови данни (прозрачност)


class CommandCenterOut(BaseModel):
    company_name: str
    currency: str
    cash: Decimal
    revenue: Decimal
    expenses: Decimal
    profit: Decimal
    receivables: Decimal
    payables: Decimal
    pending_documents: int
    summary: str
    recommendations: list[str] = []
    risks: list[str] = []
