"""Бизнес логика за платежни предложения (maker-checker)."""
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.companies.models import Company
from app.modules.counterparties.models import Counterparty, CounterpartyType
from app.modules.payments.models import PaymentProposal, PaymentStatus
from app.modules.payments.schemas import PaymentCreate

# Праг за маркер „висока стойност" (за MVP константа; подлежи на конфигуриране).
_HIGH_VALUE = Decimal("5000.00")


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def prepare(db: Session, company: Company, user_id: uuid.UUID, data: PaymentCreate) -> PaymentProposal:
    cp = db.get(Counterparty, data.counterparty_id)
    if cp is None or cp.company_id != company.id:
        raise _err("Контрагентът не съществува в тази компания")
    if cp.type not in (CounterpartyType.SUPPLIER, CounterpartyType.BOTH):
        raise _err("Контрагентът не е доставчик")

    known_ibans = {ba.iban for ba in cp.bank_accounts}
    primary = next((ba.iban for ba in cp.bank_accounts if ba.is_primary), None)
    if primary is None and cp.bank_accounts:
        primary = cp.bank_accounts[0].iban
    iban = (data.recipient_iban.replace(" ", "").upper() if data.recipient_iban else None) or primary

    risk_flags: list[str] = []
    if not iban:
        risk_flags.append("MISSING_IBAN")
    elif known_ibans and iban not in known_ibans:
        risk_flags.append("IBAN_MISMATCH")  # IBAN, различен от известните за контрагента
    if data.amount >= _HIGH_VALUE:
        risk_flags.append("HIGH_VALUE")

    proposal = PaymentProposal(
        company_id=company.id,
        counterparty_id=cp.id,
        recipient_name=cp.name,
        recipient_iban=iban,
        amount=data.amount,
        currency=(data.currency or company.base_currency).upper(),
        due_date=data.due_date,
        priority=data.priority,
        reference=data.reference,
        notes=data.notes,
        status=PaymentStatus.PREPARED,
        risk_flags=risk_flags,
        prepared_by_id=user_id,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def list_payments(
    db: Session, company_id: uuid.UUID, status_filter: PaymentStatus | None = None
) -> list[PaymentProposal]:
    stmt = select(PaymentProposal).where(PaymentProposal.company_id == company_id)
    if status_filter is not None:
        stmt = stmt.where(PaymentProposal.status == status_filter)
    return list(db.scalars(stmt.order_by(PaymentProposal.created_at.desc())))


def get_payment(db: Session, company_id: uuid.UUID, pid: uuid.UUID) -> PaymentProposal:
    p = db.get(PaymentProposal, pid)
    if p is None or p.company_id != company_id:
        raise _err("Платежното предложение не е намерено", status.HTTP_404_NOT_FOUND)
    return p


def approve(db: Session, company_id: uuid.UUID, pid: uuid.UUID, user_id: uuid.UUID) -> PaymentProposal:
    p = get_payment(db, company_id, pid)
    if p.status != PaymentStatus.PREPARED:
        raise _err("Само подготвено предложение може да бъде одобрено", status.HTTP_409_CONFLICT)
    if p.prepared_by_id == user_id:
        raise _err(
            "Не можеш да одобриш собственото си предложение (segregation of duties)",
            status.HTTP_403_FORBIDDEN,
        )
    p.status = PaymentStatus.APPROVED
    p.approved_by_id = user_id
    db.commit()
    db.refresh(p)
    return p


def reject(
    db: Session, company_id: uuid.UUID, pid: uuid.UUID, user_id: uuid.UUID, reason: str
) -> PaymentProposal:
    p = get_payment(db, company_id, pid)
    if p.status != PaymentStatus.PREPARED:
        raise _err("Само подготвено предложение може да бъде отхвърлено", status.HTTP_409_CONFLICT)
    p.status = PaymentStatus.REJECTED
    p.rejection_reason = reason
    db.commit()
    db.refresh(p)
    return p


def cancel(db: Session, company_id: uuid.UUID, pid: uuid.UUID) -> PaymentProposal:
    p = get_payment(db, company_id, pid)
    if p.status != PaymentStatus.PREPARED:
        raise _err("Само подготвено предложение може да бъде отменено", status.HTTP_409_CONFLICT)
    p.status = PaymentStatus.CANCELLED
    db.commit()
    db.refresh(p)
    return p
