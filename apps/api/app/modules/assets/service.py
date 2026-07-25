"""Бизнес логика: дълготрайни активи и линейна амортизация."""
import calendar
import datetime as dt
import uuid
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.accounting.models import Account, JournalType
from app.modules.accounting.schemas import JournalEntryCreate, JournalLineIn
from app.modules.accounting.service import create_entry, post_entry
from app.modules.assets.models import (
    ZERO,
    AssetStatus,
    DepreciationEntry,
    FixedAsset,
)
from app.modules.assets.schemas import (
    DepreciationProposal,
    FixedAssetCreate,
    ScheduleLine,
)
from app.modules.companies.models import Company

_CENT = Decimal("0.01")


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def _validate_account(db: Session, company_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.company_id != company_id:
        raise _err("Сметката не съществува в тази компания")
    if account.is_group:
        raise _err(f"Сметка {account.code} е обобщаваща — избери аналитична")
    return account


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


def _monthly_amount(asset: FixedAsset) -> Decimal:
    return _q(asset.depreciable_base / Decimal(asset.useful_life_months))


# ============================ CRUD ============================
def create_asset(db: Session, company_id: uuid.UUID, data: FixedAssetCreate) -> FixedAsset:
    if data.residual_value >= data.initial_cost:
        raise _err("Остатъчната стойност трябва да е под първоначалната")
    for field in ("gl_asset_account_id", "gl_expense_account_id", "gl_accum_account_id"):
        acc_id = getattr(data, field)
        if acc_id is not None:
            _validate_account(db, company_id, acc_id)

    asset = FixedAsset(company_id=company_id, **data.model_dump())
    db.add(asset)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _err(f"Актив с инвентарен номер {data.inventory_number} вече съществува", status.HTTP_409_CONFLICT)
    db.refresh(asset)
    return asset


def list_assets(db: Session, company_id: uuid.UUID) -> list[FixedAsset]:
    return list(
        db.scalars(
            select(FixedAsset).where(FixedAsset.company_id == company_id).order_by(FixedAsset.inventory_number)
        )
    )


def get_asset(db: Session, company_id: uuid.UUID, asset_id: uuid.UUID) -> FixedAsset:
    asset = db.get(FixedAsset, asset_id)
    if asset is None or asset.company_id != company_id:
        raise _err("Активът не е намерен", status.HTTP_404_NOT_FOUND)
    return asset


# ============================ Амортизация ============================
def schedule(db: Session, company_id: uuid.UUID, asset_id: uuid.UUID) -> list[ScheduleLine]:
    asset = get_asset(db, company_id, asset_id)
    monthly = _monthly_amount(asset)
    base = asset.depreciable_base
    life = asset.useful_life_months
    lines: list[ScheduleLine] = []
    cumulative = ZERO
    for i in range(life):
        year, month = _add_months(asset.in_service_date.year, asset.in_service_date.month, i)
        amount = monthly if i < life - 1 else _q(base - monthly * (life - 1))  # последният поема закръглянето
        cumulative += amount
        lines.append(ScheduleLine(year=year, month=month, amount=amount, cumulative=cumulative))
    return lines


def _posted_asset_ids(db: Session, company_id: uuid.UUID, year: int, month: int) -> set[uuid.UUID]:
    rows = db.scalars(
        select(DepreciationEntry.asset_id).where(
            DepreciationEntry.company_id == company_id,
            DepreciationEntry.year == year,
            DepreciationEntry.month == month,
        )
    )
    return set(rows)


def depreciation_run(
    db: Session, company_id: uuid.UUID, year: int, month: int
) -> list[DepreciationProposal]:
    """Предложения за месечна амортизация за активите (без осчетоводяване)."""
    already = _posted_asset_ids(db, company_id, year, month)
    proposals: list[DepreciationProposal] = []
    for asset in list_assets(db, company_id):
        if asset.status != AssetStatus.ACTIVE or asset.id in already:
            continue
        if asset.gl_expense_account_id is None or asset.gl_accum_account_id is None:
            continue
        remaining = asset.depreciable_base - asset.accumulated_depreciation
        if remaining <= ZERO:
            continue
        amount = min(_monthly_amount(asset), remaining)
        proposals.append(
            DepreciationProposal(
                asset_id=asset.id,
                inventory_number=asset.inventory_number,
                name=asset.name,
                amount=amount,
            )
        )
    return proposals


def depreciate(
    db: Session,
    company: Company,
    asset_id: uuid.UUID,
    year: int,
    month: int,
    amount: Decimal | None,
    user_id: uuid.UUID,
) -> DepreciationEntry:
    asset = get_asset(db, company.id, asset_id)
    if asset.status != AssetStatus.ACTIVE:
        raise _err("Активът не е в експлоатация", status.HTTP_409_CONFLICT)
    if asset.gl_expense_account_id is None or asset.gl_accum_account_id is None:
        raise _err("Задай сметки за амортизация (разход и натрупана) на актива")
    if asset.id in _posted_asset_ids(db, company.id, year, month):
        raise _err("Амортизацията за този период вече е осчетоводена", status.HTTP_409_CONFLICT)

    remaining = asset.depreciable_base - asset.accumulated_depreciation
    if remaining <= ZERO:
        raise _err("Активът е напълно амортизиран")
    amt = min(amount if amount is not None else _monthly_amount(asset), remaining)
    amt = _q(amt)
    if amt <= ZERO:
        raise _err("Сумата на амортизацията трябва да е положителна")

    last_day = calendar.monthrange(year, month)[1]
    entry_data = JournalEntryCreate(
        document_date=dt.date(year, month, last_day),
        journal=JournalType.DEPRECIATION,
        document_type="Амортизация",
        document_number=f"AMO-{asset.inventory_number}-{year}{month:02d}",
        description=f"Амортизация на {asset.name}",
        lines=[
            JournalLineIn(account_id=asset.gl_expense_account_id, debit=amt, credit=ZERO),
            JournalLineIn(account_id=asset.gl_accum_account_id, debit=ZERO, credit=amt),
        ],
    )
    entry = create_entry(db, company, user_id, entry_data)
    post_entry(db, company.id, entry.id, user_id)

    depr = DepreciationEntry(
        company_id=company.id,
        asset_id=asset.id,
        year=year,
        month=month,
        amount=amt,
        journal_entry_id=entry.id,
        created_by_id=user_id,
    )
    asset.accumulated_depreciation += amt
    db.add(depr)
    db.commit()
    db.refresh(depr)
    return depr


def dispose(db: Session, company_id: uuid.UUID, asset_id: uuid.UUID, on_date: dt.date) -> FixedAsset:
    asset = get_asset(db, company_id, asset_id)
    if asset.status != AssetStatus.ACTIVE:
        raise _err("Активът вече не е в експлоатация", status.HTTP_409_CONFLICT)
    asset.status = AssetStatus.DISPOSED
    asset.disposal_date = on_date
    db.commit()
    db.refresh(asset)
    return asset
