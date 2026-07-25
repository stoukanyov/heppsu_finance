"""Pydantic схеми за AI модула."""
import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.accounting.schemas import JournalEntryOut  # по-долен слой — без цикъл


class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    model: str
    data: dict
    created_at: dt.datetime


class ExpenseClassificationOut(BaseModel):
    """AI преценка за данъчното третиране на разход (по ЗКПО и ЗДДС)."""

    account_code: str                          # избраната разходна сметка
    account_rationale: str | None = None
    is_deductible: bool                        # признат ли е разходът за данъчни цели
    deductible_ratio: float | None = None      # 0..1 при частично признаване
    tax_rationale: str                         # обосновка по ЗКПО
    vat_credit: str                            # FULL | PARTIAL | NONE | UNKNOWN
    vat_rationale: str | None = None
    expense_category: str | None = None
    confidence: float = 0.0
    warnings: list[str] = []


class PostingProposalOut(BaseModel):
    """Предложение за осчетоводяване: чернова статия + защо и колко сигурно.

    По подразбиране AI само предлага (DRAFT). Ако компанията е разрешила
    авто-осчетоводяване и увереността е достатъчна, статията се осчетоводява и
    `auto_posted` е True.
    """

    entry: JournalEntryOut | None   # статия (DRAFT или осчетоводена); None, ако не може да се предложи
    confidence: float               # 0..1
    rationale: str                  # кратко обяснение на български защо тези сметки
    warnings: list[str] = []        # напр. „ДДС кодът е предположен", „липсва доставчик"
    classification: ExpenseClassificationOut | None = None  # AI данъчна преценка
    auto_posted: bool = False       # осчетоводена автоматично (без ръчно потвърждение)


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
