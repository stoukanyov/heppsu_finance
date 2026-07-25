"""API рутер за процедурите по възстановяване на ДДС (чл. 92 ЗДДС), tenant-scoped.

Системата подготвя и следи процедурата; подаването към НАП остава ръчно (с КЕП).
"""
import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentCompany, DbSession
from app.modules.accounting.models import AccountingPeriod
from app.modules.vat_refund import service
from app.modules.vat_refund.schemas import (
    AcceleratedCheckOut,
    AcceleratedElectionIn,
    RefundDecisionIn,
    RefundPaymentIn,
    VatRefundOverviewOut,
    VatRefundProcedureOut,
)

router = APIRouter(prefix="/vat-refunds", tags=["vat-refunds"])


def _period_code(db, company_id: uuid.UUID, period_id: uuid.UUID | None) -> str | None:
    if period_id is None:
        return None
    period = db.get(AccountingPeriod, period_id)
    return period.code if period and period.company_id == company_id else None


def _overview(db, company, proc, with_accelerated: bool = True) -> VatRefundOverviewOut:
    accelerated = None
    if with_accelerated:
        try:
            accelerated = service.check_accelerated(db, company, proc.id)
        except Exception:  # noqa: BLE001 — проверката е информативна
            accelerated = None
    second = _period_code(db, company.id, proc.second_offset_period_id)
    return VatRefundOverviewOut(
        procedure=VatRefundProcedureOut.model_validate(proc),
        origin_period_code=_period_code(db, company.id, proc.origin_period_id) or "—",
        first_offset_period_code=_period_code(db, company.id, proc.first_offset_period_id),
        second_offset_period_code=second,
        expected_completion_period_code=second,
        next_action=service.next_action(proc),
        accelerated=accelerated,
        validations=service.validate_procedure(db, company, proc),
    )


@router.post("/evaluate/{period_id}", response_model=VatRefundOverviewOut | None)
def evaluate_period(period_id: uuid.UUID, ctx: CurrentCompany, db: DbSession):
    """Проверява дали за периода възниква ДДС за възстановяване и открива процедура."""
    proc = service.evaluate_period(db, ctx.company, ctx.membership.user_id, period_id)
    if proc is None:
        return None
    return _overview(db, ctx.company, proc)


@router.get("", response_model=list[VatRefundProcedureOut])
def list_procedures(ctx: CurrentCompany, db: DbSession) -> list[VatRefundProcedureOut]:
    return [
        VatRefundProcedureOut.model_validate(p)
        for p in service.list_procedures(db, ctx.company.id)
    ]


@router.get("/{procedure_id}", response_model=VatRefundOverviewOut)
def get_procedure(procedure_id: uuid.UUID, ctx: CurrentCompany, db: DbSession):
    proc = service.get_procedure(db, ctx.company.id, procedure_id)
    return _overview(db, ctx.company, proc)


@router.post("/{procedure_id}/validate-credit", response_model=VatRefundOverviewOut)
def validate_credit(procedure_id: uuid.UUID, ctx: CurrentCompany, db: DbSession):
    """Потвърждава правото на данъчен кредит (задължителните проверки)."""
    proc = service.validate_credit(db, ctx.company, ctx.membership.user_id, procedure_id)
    return _overview(db, ctx.company, proc)


@router.post("/{procedure_id}/declare-cell-60", response_model=VatRefundOverviewOut)
def declare_cell_60(procedure_id: uuid.UUID, ctx: CurrentCompany, db: DbSession):
    proc = service.declare_in_cell_60(db, ctx.company, procedure_id)
    return _overview(db, ctx.company, proc)


@router.post("/{procedure_id}/offset/{period_id}", response_model=VatRefundOverviewOut)
def apply_offset(
    procedure_id: uuid.UUID, period_id: uuid.UUID, ctx: CurrentCompany, db: DbSession
):
    """Приспада ДДС за внасяне от последващ период (клетки 70/71)."""
    proc = service.apply_offset(db, ctx.company, procedure_id, period_id)
    return _overview(db, ctx.company, proc)


@router.get("/{procedure_id}/accelerated-check", response_model=AcceleratedCheckOut)
def accelerated_check(
    procedure_id: uuid.UUID, ctx: CurrentCompany, db: DbSession
) -> AcceleratedCheckOut:
    """Проверява 30-процентния критерий по чл. 92, ал. 3 — БЕЗ да прилага процедурата."""
    return service.check_accelerated(db, ctx.company, procedure_id)


@router.post("/{procedure_id}/elect-accelerated", response_model=VatRefundOverviewOut)
def elect_accelerated(
    procedure_id: uuid.UUID,
    data: AcceleratedElectionIn,
    ctx: CurrentCompany,
    db: DbSession,
):
    """Прилага ускорената процедура след ИЗРИЧНО потвърждение от потребителя."""
    proc = service.elect_accelerated(db, ctx.company, ctx.membership.user_id, procedure_id, data)
    return _overview(db, ctx.company, proc)


@router.post("/{procedure_id}/submit", response_model=VatRefundOverviewOut)
def submit(
    procedure_id: uuid.UUID,
    ctx: CurrentCompany,
    db: DbSession,
    submitted_on: dt.date | None = None,
):
    """Отбелязва подаването (с КЕП, извън системата) и стартира 30-дневния срок."""
    proc = service.submit(db, ctx.company, procedure_id, submitted_on)
    return _overview(db, ctx.company, proc)


@router.post("/{procedure_id}/nra-check", response_model=VatRefundOverviewOut)
def start_nra_check(
    procedure_id: uuid.UUID, ctx: CurrentCompany, db: DbSession, audit: bool = False
):
    proc = service.start_nra_check(db, ctx.company, procedure_id, audit)
    return _overview(db, ctx.company, proc)


@router.post("/{procedure_id}/decision", response_model=VatRefundOverviewOut)
def record_decision(
    procedure_id: uuid.UUID, data: RefundDecisionIn, ctx: CurrentCompany, db: DbSession
):
    proc = service.record_decision(db, ctx.company, procedure_id, data)
    return _overview(db, ctx.company, proc)


@router.post("/{procedure_id}/payment", response_model=VatRefundOverviewOut)
def record_payment(
    procedure_id: uuid.UUID, data: RefundPaymentIn, ctx: CurrentCompany, db: DbSession
):
    proc = service.record_payment(db, ctx.company, procedure_id, data)
    return _overview(db, ctx.company, proc)
