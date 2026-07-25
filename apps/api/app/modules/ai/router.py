"""API рутер за AI модула (tenant-scoped). AI само предлага — не осчетоводява."""
import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentCompany, DbSession
from app.modules.ai import service
from app.modules.ai.schemas import CfoAnswer, CfoQuestion, CommandCenterOut, ExtractionOut

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post(
    "/documents/{doc_id}/extract",
    response_model=ExtractionOut,
    status_code=status.HTTP_201_CREATED,
)
def extract_document(doc_id: uuid.UUID, ctx: CurrentCompany, db: DbSession) -> ExtractionOut:
    """Извлича данни от качен документ (OCR/vision) и го маркира за проверка."""
    extraction = service.extract_document(db, ctx.company, ctx.membership.user_id, doc_id)
    return ExtractionOut.model_validate(extraction)


@router.post("/cfo/ask", response_model=CfoAnswer)
def cfo_ask(data: CfoQuestion, ctx: CurrentCompany, db: DbSession) -> CfoAnswer:
    """AI CFO: анализ и препоръки върху финансовите данни на компанията."""
    return service.cfo_analysis(db, ctx.company, data.question, data.period_id)


@router.get("/command-center", response_model=CommandCenterOut)
def command_center(ctx: CurrentCompany, db: DbSession) -> CommandCenterOut:
    """Начален екран: финансов снапшот + AI резюме, препоръки и рискове."""
    return service.command_center(db, ctx.company)
