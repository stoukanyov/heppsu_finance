"""Бизнес логика за компании и членства."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.companies.models import Company, CompanyRole, Membership
from app.modules.companies.schemas import CompanyCreate


def create_company(db: Session, data: CompanyCreate, owner_id: uuid.UUID) -> tuple[Company, Membership]:
    """Създава компания и прави създателя ѝ OWNER (в една транзакция)."""
    company = Company(
        name=data.name,
        eik=data.eik,
        vat_number=data.vat_number,
        country=data.country.upper(),
        base_currency=data.base_currency.upper(),
        is_vat_registered=data.is_vat_registered,
    )
    db.add(company)
    db.flush()  # осигурява company.id преди създаване на членството

    membership = Membership(user_id=owner_id, company_id=company.id, role=CompanyRole.OWNER)
    db.add(membership)
    db.commit()
    db.refresh(company)
    db.refresh(membership)
    return company, membership


def list_companies_for_user(db: Session, user_id: uuid.UUID) -> list[tuple[Company, CompanyRole]]:
    rows = db.execute(
        select(Company, Membership.role)
        .join(Membership, Membership.company_id == Company.id)
        .where(Membership.user_id == user_id)
        .order_by(Company.name)
    ).all()
    return [(company, role) for company, role in rows]
