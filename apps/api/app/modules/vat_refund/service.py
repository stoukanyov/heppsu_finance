"""Логика на VAT Refund Procedure Engine (чл. 92 ЗДДС).

Управлява целия жизнен цикъл на възстановяването, а не само попълването на клетка:
възникване (клетка 60) → двумесечно приспадане (клетки 70/71) → остатък (клетка 80),
или ускорена процедура (клетка 81 / 82) при изрично решение на потребителя.

Принципи:
- Клетка 80 НЕ се попълва в първия месец — само след приключване на процедурата.
- Ускореното възстановяване не се активира автоматично: изисква потвърждение.
- Системата подготвя, но не подава декларации.
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.accounting.models import AccountingPeriod
from app.modules.companies.models import Company
from app.modules.vat import service as vat_service
from app.modules.vat_refund import eligibility as elig
from app.modules.vat_refund.models import (
    ALLOWED_TRANSITIONS,
    NraCheckStatus,
    RefundProcedureType,
    RefundStatus,
    VatRefundOffset,
    VatRefundProcedure,
)
from app.modules.vat_refund.schemas import (
    AcceleratedCheckOut,
    AcceleratedElectionIn,
    RefundDecisionIn,
    RefundPaymentIn,
    RefundValidationOut,
)

ZERO = Decimal("0.00")


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def _period(db: Session, company_id: uuid.UUID, period_id: uuid.UUID) -> AccountingPeriod:
    period = db.get(AccountingPeriod, period_id)
    if period is None or period.company_id != company_id:
        raise _err("Периодът не е намерен", status.HTTP_404_NOT_FOUND)
    return period


def _next_periods(
    db: Session, company_id: uuid.UUID, origin: AccountingPeriod, count: int = 2
) -> list[AccountingPeriod]:
    """Следващите `count` данъчни периода след периода на възникване."""
    return list(
        db.scalars(
            select(AccountingPeriod)
            .where(
                AccountingPeriod.company_id == company_id,
                AccountingPeriod.start_date > origin.start_date,
            )
            .order_by(AccountingPeriod.start_date)
            .limit(count)
        )
    )


def _submission_deadline(period: AccountingPeriod) -> dt.date:
    """Справка-декларацията се подава до 14-о число на следващия месец."""
    day_after = period.end_date + dt.timedelta(days=1)
    return dt.date(day_after.year, day_after.month, settings.VAT_SUBMISSION_DAY)


def _transition(procedure: VatRefundProcedure, target: RefundStatus) -> None:
    if target == procedure.status:
        return
    if target not in ALLOWED_TRANSITIONS.get(procedure.status, set()):
        raise _err(
            f"Недопустим преход на процедурата: {procedure.status.value} → {target.value}",
            status.HTTP_409_CONFLICT,
        )
    procedure.status = target


# ============================ Възникване ============================
def evaluate_period(
    db: Session, company: Company, user_id: uuid.UUID, period_id: uuid.UUID
) -> VatRefundProcedure | None:
    """Проверява дали за периода възниква ДДС за възстановяване и открива процедура.

    Връща None, ако резултатът е за внасяне или нула — тогава няма процедура.
    """
    period = _period(db, company.id, period_id)
    existing = db.scalar(
        select(VatRefundProcedure).where(
            VatRefundProcedure.company_id == company.id,
            VatRefundProcedure.origin_period_id == period_id,
        )
    )
    if existing is not None:
        return existing

    vat_return = vat_service.get_vat_return(db, company.id, period_id)
    refundable = Decimal(vat_return.vat_refundable)
    if refundable <= ZERO:
        return None

    firsts = _next_periods(db, company.id, period, 2)
    procedure = VatRefundProcedure(
        company_id=company.id,
        origin_period_id=period_id,
        original_refund_amount=refundable,
        remaining_refund=refundable,
        procedure_type=RefundProcedureType.STANDARD,
        legal_basis="чл. 92, ал. 1 ЗДДС",
        status=RefundStatus.CALCULATED,
        declaration_cell="60",
        first_offset_period_id=firsts[0].id if len(firsts) > 0 else None,
        second_offset_period_id=firsts[1].id if len(firsts) > 1 else None,
        submission_deadline=_submission_deadline(period),
        created_by_id=user_id,
    )
    db.add(procedure)
    db.commit()
    db.refresh(procedure)
    return procedure


def get_procedure(db: Session, company_id: uuid.UUID, procedure_id: uuid.UUID) -> VatRefundProcedure:
    proc = db.get(VatRefundProcedure, procedure_id)
    if proc is None or proc.company_id != company_id:
        raise _err("Процедурата не е намерена", status.HTTP_404_NOT_FOUND)
    return proc


def list_procedures(db: Session, company_id: uuid.UUID) -> list[VatRefundProcedure]:
    return list(
        db.scalars(
            select(VatRefundProcedure)
            .where(VatRefundProcedure.company_id == company_id)
            .order_by(VatRefundProcedure.created_at.desc())
        )
    )


def open_procedure_for_company(
    db: Session, company_id: uuid.UUID
) -> VatRefundProcedure | None:
    """Активната (незавършена) процедура — за проверка „има ли отворено приспадане"."""
    closed = (RefundStatus.PAID, RefundStatus.REFUSED, RefundStatus.CLOSED)
    return db.scalar(
        select(VatRefundProcedure)
        .where(
            VatRefundProcedure.company_id == company_id,
            VatRefundProcedure.status.notin_(closed),
        )
        .order_by(VatRefundProcedure.created_at)
    )


# ============================ Валидации ============================
def validate_procedure(
    db: Session, company: Company, procedure: VatRefundProcedure
) -> list[RefundValidationOut]:
    """Задължителните проверки преди да се разреши възстановяване."""
    out: list[RefundValidationOut] = []
    period = _period(db, company.id, procedure.origin_period_id)

    if not company.is_vat_registered:
        out.append(RefundValidationOut(
            level="ERROR", code="NOT_VAT_REGISTERED",
            message="Дружеството не е регистрирано по ЗДДС — възстановяване не е възможно.",
        ))
    if company.vat_registration_date and period.end_date < company.vat_registration_date:
        out.append(RefundValidationOut(
            level="ERROR", code="PERIOD_BEFORE_VAT_REGISTRATION",
            message=(
                f"Периодът {period.code} е преди регистрацията по ЗДДС "
                f"({company.vat_registration_date.isoformat()})."
            ),
        ))

    # Контролите на ДДС дневниците (дублирани документи, липсващ VIES, разминаване в ставки)
    for control in vat_service.vat_period_controls(db, company.id, procedure.origin_period_id):
        out.append(RefundValidationOut(
            level=control.level, code=control.code, message=control.message
        ))

    # Съответствие между декларацията и дневниците (клетки 20 и 40)
    declaration = vat_service.get_vat_declaration(db, company.id, procedure.origin_period_id)
    cells = {c.cell: Decimal(c.amount) for c in declaration.cells}
    vat_return = vat_service.get_vat_return(db, company.id, procedure.origin_period_id)
    if cells.get("20") != Decimal(vat_return.sales.total_vat):
        out.append(RefundValidationOut(
            level="ERROR", code="CELL20_LEDGER_MISMATCH",
            message="Клетка 20 не съответства на дневника за продажбите.",
        ))
    if cells.get("40") != Decimal(vat_return.purchases.total_credit):
        out.append(RefundValidationOut(
            level="ERROR", code="CELL40_LEDGER_MISMATCH",
            message="Клетка 40 не съответства на дневника за покупките.",
        ))
    if cells.get("60") != procedure.original_refund_amount:
        out.append(RefundValidationOut(
            level="WARNING", code="CELL60_AMOUNT_CHANGED",
            message=(
                f"Клетка 60 сега е {cells.get('60')}, а процедурата е открита за "
                f"{procedure.original_refund_amount} — преизчисли процедурата."
            ),
        ))

    # Друга отворена процедура пречи на реда на приспадане
    other = db.scalar(
        select(VatRefundProcedure).where(
            VatRefundProcedure.company_id == company.id,
            VatRefundProcedure.id != procedure.id,
            VatRefundProcedure.status.notin_(
                (RefundStatus.PAID, RefundStatus.REFUSED, RefundStatus.CLOSED)
            ),
        )
    )
    if other is not None:
        out.append(RefundValidationOut(
            level="WARNING", code="OTHER_OPEN_PROCEDURE",
            message="Има друга отворена процедура по приспадане — провери реда на погасяване.",
        ))

    if not out:
        out.append(RefundValidationOut(
            level="INFO", code="OK", message="Всички задължителни проверки са преминати.",
        ))
    return out


def validate_credit(
    db: Session, company: Company, user_id: uuid.UUID, procedure_id: uuid.UUID
) -> VatRefundProcedure:
    """Потвърждава данъчния кредит и придвижва процедурата (CALCULATED → VALIDATED)."""
    proc = get_procedure(db, company.id, procedure_id)
    problems = [v for v in validate_procedure(db, company, proc) if v.level == "ERROR"]
    if problems:
        raise _err(
            "Има блокиращи грешки: " + "; ".join(p.message for p in problems),
        )
    _transition(proc, RefundStatus.VAT_CREDIT_VALIDATED)
    db.commit()
    db.refresh(proc)
    return proc


def declare_in_cell_60(
    db: Session, company: Company, procedure_id: uuid.UUID
) -> VatRefundProcedure:
    """Декларира сумата в клетка 60 (текущ резултат за възстановяване)."""
    proc = get_procedure(db, company.id, procedure_id)
    _transition(proc, RefundStatus.DECLARED_IN_CELL_60)
    proc.declaration_cell = "60"
    db.commit()
    db.refresh(proc)
    return proc


# ============================ Приспадане (клетки 70/71) ============================
def apply_offset(
    db: Session, company: Company, procedure_id: uuid.UUID, period_id: uuid.UUID
) -> VatRefundProcedure:
    """Приспада ДДС за внасяне от даден последващ период срещу остатъка."""
    proc = get_procedure(db, company.id, procedure_id)
    if proc.procedure_type != RefundProcedureType.STANDARD:
        raise _err("Приспадането е част само от стандартната процедура по чл. 92, ал. 1.")

    period = _period(db, company.id, period_id)
    expected = {proc.first_offset_period_id: 1, proc.second_offset_period_id: 2}
    sequence = expected.get(period_id)
    if sequence is None:
        raise _err(
            "Периодът не е един от двата последващи периода на приспадане за тази процедура."
        )
    if sequence == 2 and proc.status == RefundStatus.DECLARED_IN_CELL_60:
        raise _err("Първо приспадни първия последващ период.")

    if db.scalar(
        select(VatRefundOffset).where(
            VatRefundOffset.procedure_id == proc.id, VatRefundOffset.period_id == period_id
        )
    ) is not None:
        raise _err(f"Периодът {period.code} вече е приспаднат.", status.HTTP_409_CONFLICT)

    vat_return = vat_service.get_vat_return(db, company.id, period_id)
    payable = Decimal(vat_return.vat_payable)
    offset_amount = min(payable, proc.remaining_refund)

    db.add(VatRefundOffset(
        procedure_id=proc.id,
        period_id=period_id,
        sequence=sequence,
        vat_payable_in_period=payable,
        amount=offset_amount,                              # клетка 70
        payable_remaining=payable - offset_amount,          # клетка 71
        refund_remaining_after=proc.remaining_refund - offset_amount,
    ))
    proc.amount_offset += offset_amount
    proc.remaining_refund -= offset_amount

    _transition(proc, RefundStatus.OFFSET_PERIOD_1 if sequence == 1 else RefundStatus.OFFSET_PERIOD_2)
    # Изчерпаният остатък приключва процедурата — няма какво да се възстановява.
    if proc.remaining_refund <= ZERO:
        proc.remaining_refund = ZERO
        proc.declaration_cell = None
        proc.notes = "Остатъкът е изцяло приспаднат — няма сума за възстановяване."
        proc.status = RefundStatus.CLOSED
    elif sequence == 2:
        proc.status = RefundStatus.READY_FOR_CELL_80
        proc.declaration_cell = "80"
        proc.submission_deadline = _submission_deadline(period)
    db.commit()
    db.refresh(proc)
    return proc


# ============================ Ускорена процедура ============================
def check_accelerated(
    db: Session, company: Company, procedure_id: uuid.UUID
) -> AcceleratedCheckOut:
    """Проверява 30-процентния критерий, без да прилага процедурата."""
    proc = get_procedure(db, company.id, procedure_id)
    period = _period(db, company.id, proc.origin_period_id)
    result = elig.zero_rate_ratio(db, company.id, period.start_date)

    proc.zero_rate_ratio = result.ratio
    proc.accelerated_eligible = result.eligible
    if result.eligible and proc.status == RefundStatus.CALCULATED:
        pass  # преходът става само при изрично решение (elect_accelerated)
    db.commit()

    return AcceleratedCheckOut(
        eligible=result.eligible,
        zero_rate_amount=result.zero_rate_amount,
        taxable_amount=result.taxable_amount,
        ratio_percent=result.ratio_percent,
        threshold_percent=(result.threshold * Decimal("100")).quantize(Decimal("0.1")),
        period_from=result.period_from,
        period_to=result.period_to,
        legal_basis=result.legal_basis,
        reasons=result.reasons,
    )


def elect_accelerated(
    db: Session,
    company: Company,
    user_id: uuid.UUID,
    procedure_id: uuid.UUID,
    data: AcceleratedElectionIn,
) -> VatRefundProcedure:
    """Прилага ускорената процедура — САМО след изрично решение на потребителя.

    Желанието се удостоверява чрез самото деклариране в клетка 81 (или 82 при
    разрешение по чл. 166 ЗДДС).
    """
    proc = get_procedure(db, company.id, procedure_id)
    if not data.confirm:
        raise _err("Ускорената процедура изисква изрично потвърждение.")

    with_permit = bool(data.investment_permit_number)
    if not with_permit:
        check = check_accelerated(db, company, procedure_id)
        if not check.eligible:
            raise _err(
                "Условията по чл. 92, ал. 3 не са изпълнени: "
                f"нулева ставка {check.ratio_percent}% срещу изискуеми {check.threshold_percent}%."
            )

    _transition(proc, RefundStatus.ACCELERATED_ELIGIBILITY_CONFIRMED)
    _transition(proc, RefundStatus.USER_APPROVED)
    proc.user_approved_by_id = user_id
    proc.user_approved_at = dt.datetime.now(dt.UTC)

    if with_permit:
        proc.procedure_type = RefundProcedureType.INVESTMENT_PERMIT
        proc.legal_basis = "чл. 92, ал. 4 ЗДДС (разрешение по чл. 166)"
        proc.declaration_cell = "82"
        proc.nra_act_reference = data.investment_permit_number
        _transition(proc, RefundStatus.DECLARED_IN_CELL_82)
    else:
        proc.procedure_type = RefundProcedureType.ACCELERATED
        proc.legal_basis = "чл. 92, ал. 3 ЗДДС"
        proc.declaration_cell = "81"
        _transition(proc, RefundStatus.DECLARED_IN_CELL_81)

    # Ускорената процедура пропуска двумесечното приспадане.
    proc.first_offset_period_id = None
    proc.second_offset_period_id = None
    db.commit()
    db.refresh(proc)
    return proc


# ============================ Подаване и решения на НАП ============================
def submit(
    db: Session, company: Company, procedure_id: uuid.UUID, submitted_on: dt.date | None = None
) -> VatRefundProcedure:
    """Отбелязва подаването и стартира 30-дневния срок за възстановяване."""
    proc = get_procedure(db, company.id, procedure_id)
    if proc.declaration_cell not in ("80", "81", "82"):
        raise _err(
            "Възстановяване се заявява в клетка 80, 81 или 82 — процедурата още не е готова."
        )
    _transition(proc, RefundStatus.SUBMITTED_FOR_REFUND)
    proc.submission_date = submitted_on or dt.date.today()
    proc.expected_refund_deadline = proc.submission_date + dt.timedelta(
        days=settings.VAT_REFUND_DEADLINE_DAYS
    )
    db.commit()
    db.refresh(proc)
    return proc


def start_nra_check(
    db: Session, company: Company, procedure_id: uuid.UUID, audit: bool = False
) -> VatRefundProcedure:
    proc = get_procedure(db, company.id, procedure_id)
    _transition(proc, RefundStatus.UNDER_NRA_CHECK)
    proc.nra_check_status = NraCheckStatus.AUDIT if audit else NraCheckStatus.CHECK
    db.commit()
    db.refresh(proc)
    return proc


def record_decision(
    db: Session, company: Company, procedure_id: uuid.UUID, data: RefundDecisionIn
) -> VatRefundProcedure:
    """Записва решението на НАП: одобрено, частично, отказано или прихванато."""
    proc = get_procedure(db, company.id, procedure_id)
    if data.nra_act_reference:
        proc.nra_act_reference = data.nra_act_reference
    if data.notes:
        proc.notes = data.notes
    if data.nra_check_status:
        proc.nra_check_status = data.nra_check_status
    if data.offset_against_public_liabilities:
        proc.offset_against_public_liabilities = data.offset_against_public_liabilities

    approved = data.approved_amount
    if approved is None:
        target = RefundStatus.OFFSET_BY_NRA if data.offset_against_public_liabilities else RefundStatus.APPROVED
    elif approved <= ZERO:
        target = RefundStatus.REFUSED
    elif approved < proc.remaining_refund:
        target = RefundStatus.PARTIALLY_APPROVED
    else:
        target = RefundStatus.APPROVED
    _transition(proc, target)
    db.commit()
    db.refresh(proc)
    return proc


def record_payment(
    db: Session, company: Company, procedure_id: uuid.UUID, data: RefundPaymentIn
) -> VatRefundProcedure:
    """Отбелязва реалното получаване на сумата (или прихващането ѝ)."""
    proc = get_procedure(db, company.id, procedure_id)
    proc.amount_paid = data.amount_paid
    if data.nra_act_reference:
        proc.nra_act_reference = data.nra_act_reference
    proc.nra_check_status = NraCheckStatus.COMPLETED
    _transition(proc, RefundStatus.PAID)
    db.commit()
    db.refresh(proc)
    return proc


# ============================ Обобщение за екрана ============================
_NEXT_ACTION = {
    RefundStatus.CALCULATED: "Потвърди данъчния кредит (валидации).",
    RefundStatus.VAT_CREDIT_VALIDATED: "Декларирай сумата в клетка 60 за периода на възникване.",
    RefundStatus.DECLARED_IN_CELL_60: "Приспадни ДДС за внасяне от първия последващ период.",
    RefundStatus.OFFSET_PERIOD_1: "Приспадни ДДС за внасяне от втория последващ период.",
    RefundStatus.OFFSET_PERIOD_2: "Процедурата приключва — подготви клетка 80.",
    RefundStatus.READY_FOR_CELL_80: "Декларирай остатъка в клетка 80 и подай декларацията.",
    RefundStatus.ACCELERATED_ELIGIBILITY_CONFIRMED: "Изисква се изрично потвърждение за клетка 81.",
    RefundStatus.USER_APPROVED: "Декларирай сумата в клетка 81 (или 82 при разрешение).",
    RefundStatus.DECLARED_IN_CELL_81: "Подай декларацията — 30-дневен срок за възстановяване.",
    RefundStatus.DECLARED_IN_CELL_82: "Подай декларацията по разрешението (чл. 166).",
    RefundStatus.SUBMITTED_FOR_REFUND: "Изчаквай проверка или превод от НАП.",
    RefundStatus.UNDER_NRA_CHECK: "Отрази решението на НАП, когато бъде получено.",
    RefundStatus.APPROVED: "Отбележи получената сума.",
    RefundStatus.PARTIALLY_APPROVED: "Отбележи получената част и прегледай отказаната.",
    RefundStatus.OFFSET_BY_NRA: "Сумата е прихваната срещу публични задължения.",
    RefundStatus.REFUSED: "Възстановяването е отказано — прегледай мотивите.",
    RefundStatus.PAID: "Процедурата е изпълнена.",
    RefundStatus.CLOSED: "Процедурата е приключена.",
}


def next_action(proc: VatRefundProcedure) -> str:
    return _NEXT_ACTION.get(proc.status, "—")
