"""Бизнес логика на модул „Оферти": номер, срок на валидност, сметка, регистър."""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.modules.companies.models import Company
from app.modules.counterparties.models import Counterparty, CounterpartyType
from app.modules.offers import markup
from app.modules.offers.models import ZERO, Offer, OfferLine, OfferStatus
from app.modules.offers.schemas import (
    OfferCreate,
    OfferLineIn,
    OfferPreviewRequest,
    OfferUpdate,
)

_CENT = Decimal("0.01")


def _q(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(_CENT, rounding=ROUND_HALF_UP)


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def valid_until(issue_date: dt.date, validity_days: int) -> dt.date:
    """Крайната дата: календарни дни след датата на изготвяне.

    Денят на изготвяне не се брои — оферта, изготвена днес с валидност 30 дни,
    е валидна до 30 дни напред.
    """
    return issue_date + dt.timedelta(days=validity_days)


def totals(lines: list[OfferLineIn], vat_rate: Decimal) -> tuple[Decimal, Decimal, Decimal, list[Decimal]]:
    """Данъчна основа, ДДС, общо и стойността на всеки ред.

    Всеки ред се закръгля до стотинка поотделно и основата е сумата от
    закръглените редове — така написаното в таблицата се сбира до тотала,
    вместо да се различава с една стотинка от него.
    """
    nets = [_q(Decimal(line.quantity) * Decimal(line.unit_price)) for line in lines]
    subtotal = _q(sum(nets, ZERO))
    vat_amount = _q(subtotal * Decimal(vat_rate) / Decimal("100"))
    return subtotal, vat_amount, _q(subtotal + vat_amount), nets


def _next_number(db: Session, company_id: uuid.UUID) -> int:
    current = db.scalar(select(func.max(Offer.number)).where(Offer.company_id == company_id))
    return (current or 0) + 1


def _customer(db: Session, company_id: uuid.UUID, counterparty_id: uuid.UUID) -> Counterparty:
    cp = db.get(Counterparty, counterparty_id)
    if cp is None or cp.company_id != company_id:
        raise _err("Клиентът не съществува в тази компания")
    if cp.type not in (CounterpartyType.CUSTOMER, CounterpartyType.BOTH):
        raise _err("Контрагентът не е клиент")
    return cp


def _replace_lines(offer: Offer, lines: list[OfferLineIn], nets: list[Decimal]) -> None:
    offer.lines.clear()
    for index, (line, net) in enumerate(zip(lines, nets, strict=True), start=1):
        offer.lines.append(
            OfferLine(
                line_no=index,
                description=line.description,
                unit=line.unit,
                quantity=line.quantity,
                unit_price=line.unit_price,
                line_net=net,
            )
        )


def create_offer(db: Session, company: Company, user_id: uuid.UUID, data: OfferCreate) -> Offer:
    _customer(db, company.id, data.counterparty_id)
    subtotal, vat_amount, total, nets = totals(data.lines, data.vat_rate)

    offer = Offer(
        company_id=company.id,
        counterparty_id=data.counterparty_id,
        number=_next_number(db, company.id),
        title=data.title,
        issue_date=data.issue_date,
        validity_days=data.validity_days,
        valid_until=valid_until(data.issue_date, data.validity_days),
        body=data.body,
        currency=(data.currency or company.base_currency),
        vat_rate=data.vat_rate,
        subtotal=subtotal,
        vat_amount=vat_amount,
        total=total,
        status=OfferStatus.DRAFT,
        created_by_id=user_id,
    )
    _replace_lines(offer, data.lines, nets)
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer


def get_offer(db: Session, company_id: uuid.UUID, offer_id: uuid.UUID) -> Offer:
    offer = db.scalar(
        select(Offer)
        .options(selectinload(Offer.lines))
        .where(Offer.id == offer_id, Offer.company_id == company_id)
    )
    if offer is None:
        raise _err("Офертата не е намерена", status.HTTP_404_NOT_FOUND)
    return offer


def list_offers(
    db: Session,
    company_id: uuid.UUID,
    counterparty_id: uuid.UUID | None = None,
    status_filter: OfferStatus | None = None,
) -> list[Offer]:
    """Регистърът на офертите, най-новата първа; по избор филтриран по клиент."""
    query = (
        select(Offer)
        .options(selectinload(Offer.lines))
        .where(Offer.company_id == company_id)
        .order_by(Offer.number.desc())
    )
    if counterparty_id is not None:
        query = query.where(Offer.counterparty_id == counterparty_id)
    if status_filter is not None:
        query = query.where(Offer.status == status_filter)
    return list(db.scalars(query))


def update_offer(
    db: Session, company_id: uuid.UUID, offer_id: uuid.UUID, data: OfferUpdate
) -> Offer:
    offer = get_offer(db, company_id, offer_id)

    if data.counterparty_id is not None:
        _customer(db, company_id, data.counterparty_id)
        offer.counterparty_id = data.counterparty_id
    if data.title is not None:
        offer.title = data.title
    if data.body is not None:
        offer.body = data.body
    if data.status is not None:
        offer.status = data.status
    if data.vat_rate is not None:
        offer.vat_rate = data.vat_rate
    if data.issue_date is not None:
        offer.issue_date = data.issue_date
    if data.validity_days is not None:
        offer.validity_days = data.validity_days
    # Крайната дата се преизчислява при промяна на всяко от двете — иначе остава
    # стара и регистърът показва изтекла оферта като валидна.
    if data.issue_date is not None or data.validity_days is not None:
        offer.valid_until = valid_until(offer.issue_date, offer.validity_days)

    if data.lines is not None:
        _, _, _, nets = totals(data.lines, offer.vat_rate)
        _replace_lines(offer, data.lines, nets)

    # Сумите се пресмятат от текущите редове при всяка редакция: смяна само на
    # ДДС ставката също мести тотала.
    current = [
        OfferLineIn(
            description=line.description,
            unit=line.unit,
            quantity=line.quantity,
            unit_price=line.unit_price,
        )
        for line in offer.lines
    ]
    offer.subtotal, offer.vat_amount, offer.total, _ = totals(current, offer.vat_rate)

    db.commit()
    db.refresh(offer)
    return offer


def delete_offer(db: Session, company_id: uuid.UUID, offer_id: uuid.UUID) -> None:
    """Изтрива оферта. Няма счетоводен ефект, затова изтриването е истинско."""
    offer = get_offer(db, company_id, offer_id)
    db.delete(offer)
    db.commit()


def copy_template(db: Session, company_id: uuid.UUID, offer_id: uuid.UUID) -> dict:
    """Съдържанието на съществуваща оферта като заготовка за нова.

    Връща текста, заглавието и позициите, но **без** клиент, дата и валидност —
    те се попълват наново. Нищо не се записва: записът става, щом новата оферта
    бъде създадена.
    """
    offer = get_offer(db, company_id, offer_id)
    return {
        "source_id": offer.id,
        "source_number": offer.full_number,
        "title": offer.title,
        "body": offer.body,
        "currency": offer.currency,
        "vat_rate": offer.vat_rate,
        "lines": [
            {
                "description": line.description,
                "unit": line.unit,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
            }
            for line in offer.lines
        ],
    }


def preview(company: Company, data: OfferPreviewRequest) -> dict:
    """Готовият за рисуване документ от още незаписан текст.

    Екранът вика този път, вместо да разчита разметката сам: така прегледът и
    PDF-ът минават през един и същи парсер и не могат да се разминат.
    """
    subtotal, vat_amount, total, nets = totals(data.lines, data.vat_rate)
    blocks = markup.parse(data.body)
    until = (
        valid_until(data.issue_date, data.validity_days)
        if data.issue_date is not None and data.validity_days is not None
        else None
    )
    return {
        "blocks": [b.as_dict() for b in blocks],
        "lines": [
            {
                "line_no": index,
                "description": line.description,
                "unit": line.unit,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "line_net": net,
            }
            for index, (line, net) in enumerate(zip(data.lines, nets, strict=True), start=1)
        ],
        "has_items_marker": any(b.kind == "items" for b in blocks),
        "valid_until": until,
        "currency": data.currency or company.base_currency,
        "vat_rate": data.vat_rate,
        "subtotal": subtotal,
        "vat_amount": vat_amount,
        "total": total,
    }


def out_payload(db: Session, offer: Offer) -> dict:
    """Офертата за API-то: моделът плюс изведените полета."""
    cp = db.get(Counterparty, offer.counterparty_id)
    return {
        "id": offer.id,
        "counterparty_id": offer.counterparty_id,
        "counterparty_name": cp.name if cp else None,
        "number": offer.number,
        "full_number": offer.full_number,
        "title": offer.title,
        "issue_date": offer.issue_date,
        "validity_days": offer.validity_days,
        "valid_until": offer.valid_until,
        "is_expired": offer.is_expired(),
        "body": offer.body,
        "currency": offer.currency,
        "vat_rate": offer.vat_rate,
        "subtotal": offer.subtotal,
        "vat_amount": offer.vat_amount,
        "total": offer.total,
        "status": offer.status,
        "lines": offer.lines,
    }
