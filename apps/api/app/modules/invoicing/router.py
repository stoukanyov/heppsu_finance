"""API рутер за фактуриране (tenant-scoped)."""
import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentCompany, DbSession, require
from app.modules.counterparties.models import Counterparty
from app.modules.invoicing import service
from app.modules.invoicing.pdf import render_invoice_pdf
from app.modules.invoicing.schemas import InvoiceCreate, InvoiceOut

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED, dependencies=[require("invoices.create")])
def create_invoice(data: InvoiceCreate, ctx: CurrentCompany, db: DbSession) -> InvoiceOut:
    inv = service.create_invoice(db, ctx.company, ctx.membership.user_id, data)
    return InvoiceOut.model_validate(inv)


@router.get("", response_model=list[InvoiceOut], dependencies=[require("invoices.view")])
def list_invoices(ctx: CurrentCompany, db: DbSession) -> list[InvoiceOut]:
    return [InvoiceOut.model_validate(i) for i in service.list_invoices(db, ctx.company.id)]


@router.get("/{invoice_id}", response_model=InvoiceOut, dependencies=[require("invoices.view")])
def get_invoice(invoice_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> InvoiceOut:
    return InvoiceOut.model_validate(service.get_invoice(db, ctx.company.id, invoice_id))


@router.get("/{invoice_id}/pdf", dependencies=[require("invoices.view")])
def invoice_pdf(invoice_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> Response:
    inv = service.get_invoice(db, ctx.company.id, invoice_id)
    cp = db.get(Counterparty, inv.counterparty_id)
    pdf_bytes = render_invoice_pdf(ctx.company, inv, cp)
    fname = f"invoice-{inv.full_number or inv.id}.pdf"
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


@router.post("/{invoice_id}/issue", response_model=InvoiceOut, dependencies=[require("invoices.issue")])
def issue_invoice(invoice_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> InvoiceOut:
    inv = service.issue_invoice(db, ctx.company, invoice_id, ctx.membership.user_id)
    return InvoiceOut.model_validate(inv)


@router.post("/{invoice_id}/cancel", response_model=InvoiceOut, dependencies=[require("invoices.issue")])
def cancel_invoice(invoice_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> InvoiceOut:
    return InvoiceOut.model_validate(service.cancel_invoice(db, ctx.company.id, invoice_id))
