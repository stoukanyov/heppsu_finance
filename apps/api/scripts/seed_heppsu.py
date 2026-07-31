"""Сийд на реалната компания ХЕПСУ КОНСУЛТИНГ ЕООД с пълни реквизити.

Създава (или обновява) компанията, инициализира стандартния сметкоплан, ДДС кодовете
и фискалната година, за да е готова за работа.

Употреба (от apps/api):
    DATABASE_URL="sqlite:///./ai_finance_os.db" \
    ../../.venv/bin/python -m scripts.seed_heppsu --email ivaylo@heppsu.com --password <парола>

Ако потребителят вече съществува, паролата се игнорира и компанията се закрепва към него.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import business_today
from app.core.config import settings
from app.core.database import engine
from app.core.security import hash_password
from app.db import registry  # noqa: F401 — регистрира моделите
from app.modules.accounting import service as accounting_service
from app.modules.accounting.schemas import FiscalYearCreate
from app.modules.companies.models import Company, CompanyRole, Membership
from app.modules.identity.models import User
from app.modules.vat import service as vat_service

# ---- Реквизити по Търговския регистър (към 25.07.2026) ----
HEPPSU = {
    "name": "ХЕПСУ КОНСУЛТИНГ ЕООД",
    "name_latin": "Heppsu Consulting ltd",
    "eik": "208418861",
    "vat_number": "BG208418861",
    "country": "BG",
    "base_currency": "EUR",
    "is_vat_registered": True,
    "legal_form": "ЕООД",
    "address_city": "гр. София",
    "address_postcode": "1618",
    "address_line": "р-н Овча купел, ул. Любляна 14, ет. 1, ап. 6",
    "manager_name": "Ели Тодорова Георгиева-Стуканьова",
    "owner_name": "Ели Тодорова Георгиева-Стуканьова",
    "activity": (
        "Консултантски дейности в областта на управлението; дейности в областта на "
        "информационните технологии; информационни услуги; електронна търговия; реклама"
    ),
    "incorporation_date": dt.date(2025, 7, 29),
    # Регистрация по избор, чл. 100, ал. 1 ЗДДС
    "vat_registration_date": dt.date(2025, 8, 11),
    "share_capital": Decimal("255.00"),
}


def _get_or_create_user(db: Session, email: str, password: str | None) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        print(f"· потребител {email} вече съществува")
        return user
    if not password:
        sys.exit("Потребителят не съществува — подай --password, за да го създам.")
    user = User(email=email, hashed_password=hash_password(password), full_name="Ивайло Стуканьов")
    db.add(user)
    db.flush()
    print(f"✓ създаден потребител {email}")
    return user


def _get_or_create_company(db: Session, user: User) -> Company:
    company = db.scalar(select(Company).where(Company.eik == HEPPSU["eik"]))
    if company is None:
        company = Company(**HEPPSU)
        db.add(company)
        db.flush()
        print(f"✓ създадена компания {company.name} (ЕИК {company.eik})")
    else:
        for key, value in HEPPSU.items():
            setattr(company, key, value)
        print(f"· реквизитите на {company.name} са обновени")

    membership = db.scalar(
        select(Membership).where(
            Membership.company_id == company.id, Membership.user_id == user.id
        )
    )
    if membership is None:
        db.add(Membership(user_id=user.id, company_id=company.id, role=CompanyRole.OWNER))
        print("✓ потребителят е добавен като OWNER")
    db.flush()
    return company


def main() -> None:
    parser = argparse.ArgumentParser(description="Сийд на ХЕПСУ КОНСУЛТИНГ ЕООД")
    parser.add_argument("--email", default="ivaylo@heppsu.com")
    parser.add_argument("--password", default=None, help="само ако потребителят е нов")
    # Не `dt.date.today()`: в 00:30 софийско време на 1 януари сървърът (UTC) още е
    # в старата година и фискалната година би се създала за грешния период.
    parser.add_argument("--year", type=int, default=business_today().year)
    args = parser.parse_args()

    # В dev (SQLite) схемата се създава автоматично; в prod се разчита на Alembic.
    if settings.AUTO_CREATE_TABLES:
        from app.db.base import Base

        Base.metadata.create_all(bind=engine)

    with Session(engine) as db:
        user = _get_or_create_user(db, args.email, args.password)
        company = _get_or_create_company(db, user)
        db.commit()

        try:
            count = accounting_service.seed_standard_chart(db, company.id)
            print(f"✓ сметкоплан: {count} сметки")
        except Exception as exc:  # noqa: BLE001 — вече инициализиран
            db.rollback()
            print(f"· сметкоплан: пропуснат ({type(exc).__name__})")

        try:
            vat_service.seed_standard_vat_codes(db, company.id)
            print("✓ ДДС кодове: инициализирани")
        except Exception:  # noqa: BLE001
            db.rollback()
            print("· ДДС кодове: вече съществуват")

        try:
            accounting_service.create_fiscal_year(db, company.id, FiscalYearCreate(year=args.year))
            print(f"✓ фискална година {args.year} с 12 периода")
        except Exception:  # noqa: BLE001
            db.rollback()
            print(f"· фискална година {args.year}: вече съществува")

        print(f"\nГотово. company_id = {company.id}")


if __name__ == "__main__":
    main()
