"""Бизнес логика за контрагенти: CRUD, валидации, откриване на дубликати."""
import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.accounting.models import Account
from app.modules.counterparties.models import (
    Counterparty,
    CounterpartyBankAccount,
    CounterpartyType,
)
from app.modules.counterparties.schemas import (
    BankAccountIn,
    CounterpartyCreate,
    CounterpartyUpdate,
    DuplicateCheckRequest,
    DuplicateMatch,
)
from app.modules.vat.models import VatCode

_LEGAL_SUFFIXES = ("еоод", "оод", "ад", "еад", "ет", "дззд", "ltd", "eood", "ood")


def _err(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(status_code=code, detail=msg)


def normalize_name(name: str) -> str:
    """Нормализира наименование за сравнение: малки букви, без правна форма и пунктуация."""
    text = name.lower().strip()
    text = re.sub(r"[\"'.,\-—/]", " ", text)
    tokens = [t for t in text.split() if t not in _LEGAL_SUFFIXES]
    return " ".join(tokens)


def _validate_defaults(db: Session, company_id: uuid.UUID, data) -> None:
    if getattr(data, "default_account_id", None) is not None:
        account = db.get(Account, data.default_account_id)
        if account is None or account.company_id != company_id:
            raise _err("Стандартната сметка не съществува в тази компания")
    if getattr(data, "default_vat_code_id", None) is not None:
        code = db.get(VatCode, data.default_vat_code_id)
        if code is None or code.company_id != company_id:
            raise _err("Стандартният ДДС код не съществува в тази компания")


def _check_hard_duplicates(
    db: Session, company_id: uuid.UUID, eik: str | None, vat: str | None, exclude_id: uuid.UUID | None
) -> None:
    if not eik and not vat:
        return
    conditions = []
    if eik:
        conditions.append(Counterparty.eik == eik)
    if vat:
        conditions.append(Counterparty.vat_number == vat)
    stmt = select(Counterparty).where(Counterparty.company_id == company_id, or_(*conditions))
    for existing in db.scalars(stmt):
        if exclude_id and existing.id == exclude_id:
            continue
        if eik and existing.eik == eik:
            raise _err(f"Контрагент с ЕИК {eik} вече съществува", status.HTTP_409_CONFLICT)
        if vat and existing.vat_number == vat:
            raise _err(f"Контрагент с ДДС номер {vat} вече съществува", status.HTTP_409_CONFLICT)


def _apply_bank_accounts(counterparty: Counterparty, items: list[BankAccountIn]) -> None:
    counterparty.bank_accounts = [
        CounterpartyBankAccount(
            iban=b.iban.replace(" ", "").upper(),
            bank_name=b.bank_name,
            currency=b.currency.upper() if b.currency else None,
            is_primary=b.is_primary,
        )
        for b in items
    ]


def create_counterparty(
    db: Session, company_id: uuid.UUID, data: CounterpartyCreate
) -> Counterparty:
    _check_hard_duplicates(db, company_id, data.eik, data.vat_number, exclude_id=None)
    _validate_defaults(db, company_id, data)

    payload = data.model_dump(exclude={"bank_accounts", "email"})
    cp = Counterparty(company_id=company_id, email=str(data.email) if data.email else None, **payload)
    _apply_bank_accounts(cp, data.bank_accounts)
    db.add(cp)
    db.commit()
    db.refresh(cp)
    return cp


def list_counterparties(
    db: Session,
    company_id: uuid.UUID,
    type_filter: CounterpartyType | None = None,
    q: str | None = None,
) -> list[Counterparty]:
    stmt = select(Counterparty).where(Counterparty.company_id == company_id)
    if type_filter is not None:
        # Филтърът по клиент/доставчик включва и контрагентите тип BOTH.
        if type_filter == CounterpartyType.CUSTOMER:
            stmt = stmt.where(Counterparty.type.in_([CounterpartyType.CUSTOMER, CounterpartyType.BOTH]))
        elif type_filter == CounterpartyType.SUPPLIER:
            stmt = stmt.where(Counterparty.type.in_([CounterpartyType.SUPPLIER, CounterpartyType.BOTH]))
        else:
            stmt = stmt.where(Counterparty.type == type_filter)
    results = list(db.scalars(stmt.order_by(Counterparty.name)))
    if q:
        # Python-side търсене — коректно за кирилица (SQLite LIKE е ASCII-only).
        needle = q.lower()
        results = [
            cp
            for cp in results
            if needle in cp.name.lower()
            or (cp.eik and needle in cp.eik.lower())
            or (cp.vat_number and needle in cp.vat_number.lower())
        ]
    return results


def get_counterparty(db: Session, company_id: uuid.UUID, cp_id: uuid.UUID) -> Counterparty:
    cp = db.get(Counterparty, cp_id)
    if cp is None or cp.company_id != company_id:
        raise _err("Контрагентът не е намерен", status.HTTP_404_NOT_FOUND)
    return cp


def update_counterparty(
    db: Session, company_id: uuid.UUID, cp_id: uuid.UUID, data: CounterpartyUpdate
) -> Counterparty:
    cp = get_counterparty(db, company_id, cp_id)
    fields = data.model_dump(exclude_unset=True)

    new_eik = fields.get("eik", cp.eik)
    new_vat = fields.get("vat_number", cp.vat_number)
    if "eik" in fields or "vat_number" in fields:
        _check_hard_duplicates(db, company_id, new_eik, new_vat, exclude_id=cp.id)
    _validate_defaults(db, company_id, data)

    bank_accounts = fields.pop("bank_accounts", None)
    if "email" in fields and fields["email"] is not None:
        fields["email"] = str(fields["email"])
    for key, value in fields.items():
        setattr(cp, key, value)
    if bank_accounts is not None:
        _apply_bank_accounts(cp, [BankAccountIn(**b) for b in bank_accounts])

    db.commit()
    db.refresh(cp)
    return cp


def find_duplicates(
    db: Session, company_id: uuid.UUID, req: DuplicateCheckRequest
) -> list[DuplicateMatch]:
    """Открива потенциални дубликати по ЕИК, ДДС номер, IBAN и сходно наименование."""
    matches: dict[uuid.UUID, set[str]] = {}
    all_cps = list(db.scalars(select(Counterparty).where(Counterparty.company_id == company_id)))

    norm_target = normalize_name(req.name) if req.name else None
    iban_target = req.iban.replace(" ", "").upper() if req.iban else None

    iban_owner_ids: set[uuid.UUID] = set()
    if iban_target:
        rows = db.scalars(
            select(CounterpartyBankAccount).where(CounterpartyBankAccount.iban == iban_target)
        )
        iban_owner_ids = {r.counterparty_id for r in rows}

    for cp in all_cps:
        reasons: set[str] = set()
        if req.eik and cp.eik and cp.eik == req.eik:
            reasons.add("ЕИК")
        if req.vat_number and cp.vat_number and cp.vat_number == req.vat_number:
            reasons.add("ДДС номер")
        if norm_target and normalize_name(cp.name) == norm_target:
            reasons.add("сходно наименование")
        if cp.id in iban_owner_ids:
            reasons.add("IBAN")
        if reasons:
            matches[cp.id] = reasons

    by_id = {cp.id: cp for cp in all_cps}
    return [
        DuplicateMatch(
            id=cp_id,
            name=by_id[cp_id].name,
            eik=by_id[cp_id].eik,
            vat_number=by_id[cp_id].vat_number,
            reasons=sorted(reasons),
        )
        for cp_id, reasons in matches.items()
    ]
