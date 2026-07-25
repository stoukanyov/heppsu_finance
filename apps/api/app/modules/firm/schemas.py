"""Pydantic схеми за таблото на кантората."""
import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.modules.firm.models import TaskStatus


class ClientTotalsOut(BaseModel):
    """Какво чака работа при един клиент."""

    pending_documents: int = 0
    draft_entries: int = 0
    unreconciled_transactions: int = 0
    open_tasks: int = 0
    overdue_tasks: int = 0

    @property
    def needs_attention(self) -> bool:
        return bool(
            self.pending_documents
            or self.draft_entries
            or self.unreconciled_transactions
            or self.overdue_tasks
        )


class NextDeadlineOut(BaseModel):
    key: str
    title: str
    due_date: dt.date
    days_remaining: int
    authority: str


class ClientOverviewOut(BaseModel):
    company_id: uuid.UUID
    name: str
    eik: str | None = None
    is_vat_registered: bool = False
    last_vat_closing_at: dt.datetime | None = None
    totals: ClientTotalsOut
    next_deadline: NextDeadlineOut | None = None
    needs_attention: bool = False   # има натрупана работа (документи, чернови, банка, просрочени задачи)
    deadline_soon: bool = False     # срок до 3 дни — прогноза, не изоставане


class TaskCreate(BaseModel):
    company_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    due_date: dt.date | None = None
    assignee_id: uuid.UUID | None = None
    deadline_key: str | None = Field(default=None, max_length=100)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    due_date: dt.date | None = None
    assignee_id: uuid.UUID | None = None
    status: TaskStatus | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    title: str
    description: str | None
    due_date: dt.date | None
    status: TaskStatus
    assignee_id: uuid.UUID | None
    deadline_key: str | None
    completed_at: dt.datetime | None


class GenerateTasksRequest(BaseModel):
    company_id: uuid.UUID
    days_ahead: int = Field(default=30, ge=1, le=365)


class BulkPackagesRequest(BaseModel):
    """Групово сваляне на пакетите за НАП. Само чете — нищо не променя."""

    company_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    period_code: str = Field(pattern=r"^\d{4}-\d{2}$", description='напр. "2026-03"')
