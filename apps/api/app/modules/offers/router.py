"""API рутер за оферти (tenant-scoped)."""
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentCompany, DbSession, require
from app.modules.counterparties.models import Counterparty
from app.modules.offers import service
from app.modules.offers.models import OfferStatus
from app.modules.offers.pdf import render_offer_pdf
from app.modules.offers.schemas import (
    OfferCreate,
    OfferOut,
    OfferPreviewOut,
    OfferPreviewRequest,
    OfferUpdate,
)

router = APIRouter(prefix="/offers", tags=["offers"])


@router.post("", response_model=OfferOut, status_code=status.HTTP_201_CREATED,
             dependencies=[require("offers.manage")])
def create_offer(data: OfferCreate, ctx: CurrentCompany, db: DbSession) -> OfferOut:
    offer = service.create_offer(db, ctx.company, ctx.membership.user_id, data)
    return OfferOut.model_validate(service.out_payload(db, offer))


@router.get("", response_model=list[OfferOut], dependencies=[require("offers.view")])
def list_offers(
    ctx: CurrentCompany,
    db: DbSession,
    counterparty_id: uuid.UUID | None = None,
    status_filter: OfferStatus | None = None,
) -> list[OfferOut]:
    """Регистърът на офертите; `counterparty_id` го филтрира по клиент."""
    offers = service.list_offers(db, ctx.company.id, counterparty_id, status_filter)
    return [OfferOut.model_validate(service.out_payload(db, o)) for o in offers]


@router.post("/preview", response_model=OfferPreviewOut, dependencies=[require("offers.view")])
def preview_offer(data: OfferPreviewRequest, ctx: CurrentCompany) -> OfferPreviewOut:
    """Разчетеният текст и сметката за още незаписана оферта.

    Екранът го вика при всяка промяна: прегледът и PDF-ът минават през един и
    същи парсер, затова не могат да покажат различен документ.
    """
    return OfferPreviewOut.model_validate(service.preview(ctx.company, data))


@router.get("/{offer_id}", response_model=OfferOut, dependencies=[require("offers.view")])
def get_offer(offer_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> OfferOut:
    offer = service.get_offer(db, ctx.company.id, offer_id)
    return OfferOut.model_validate(service.out_payload(db, offer))


@router.get("/{offer_id}/copy", dependencies=[require("offers.view")])
def copy_offer(offer_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> dict:
    """Заготовка от съществуваща оферта: текстът и позициите, без клиент и дати."""
    return service.copy_template(db, ctx.company.id, offer_id)


@router.patch("/{offer_id}", response_model=OfferOut, dependencies=[require("offers.manage")])
def update_offer(
    offer_id: uuid.UUID, data: OfferUpdate, ctx: CurrentCompany, db: DbSession
) -> OfferOut:
    offer = service.update_offer(db, ctx.company.id, offer_id, data)
    return OfferOut.model_validate(service.out_payload(db, offer))


@router.delete("/{offer_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[require("offers.manage")])
def delete_offer(offer_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> Response:
    service.delete_offer(db, ctx.company.id, offer_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{offer_id}/pdf", dependencies=[require("offers.view")])
def offer_pdf(offer_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> Response:
    offer = service.get_offer(db, ctx.company.id, offer_id)
    cp = db.get(Counterparty, offer.counterparty_id)
    content = render_offer_pdf(ctx.company, offer, cp)
    filename = f"оферта-{offer.full_number}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}"},
    )
