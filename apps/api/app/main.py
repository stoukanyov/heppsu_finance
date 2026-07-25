"""FastAPI входна точка за AI Finance OS backend."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import engine
from app.core.errors import AccessDeniedError, access_denied_handler
from app.db import registry  # noqa: F401 — регистрира всички модели в metadata
from app.db.base import Base

_WEB_DIR = Path(__file__).parent / "web"


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="0.1.0",
        description="AI-базирана финансова операционна система за управление на компании.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.modules.audit.middleware import AuditMiddleware

    app.add_middleware(AuditMiddleware)

    # Локален dev: създаваме таблиците автоматично. В production → Alembic.
    if settings.AUTO_CREATE_TABLES:
        Base.metadata.create_all(bind=engine)

    app.add_exception_handler(AccessDeniedError, access_denied_handler)

    _register_routers(app)

    # Вграден Web UI (SPA), сервиран от същия origin — без нужда от Node/CORS.
    if _WEB_DIR.is_dir():

        class _NoCacheStatic(StaticFiles):
            """SPA-то е един файл — кеширането му води до стар UI след деплой."""

            def is_not_modified(self, response_headers, request_headers) -> bool:  # noqa: ANN001
                return False

            async def get_response(self, path: str, scope):  # noqa: ANN001
                response = await super().get_response(path, scope)
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                return response

        app.mount("/app", _NoCacheStatic(directory=str(_WEB_DIR), html=True), name="web")

        @app.get("/", include_in_schema=False)
        def _root() -> RedirectResponse:
            return RedirectResponse(url="/app/")

    return app


def _register_routers(app: FastAPI) -> None:
    from app.api.routes.health import router as health_router
    from app.modules.accounting.router import router as accounting_router
    from app.modules.ai.router import router as ai_router
    from app.modules.assets.router import router as assets_router
    from app.modules.audit.router import router as audit_router
    from app.modules.banking.router import router as banking_router
    from app.modules.companies.members_router import router as members_router
    from app.modules.companies.router import router as companies_router
    from app.modules.counterparties.router import router as counterparties_router
    from app.modules.deadlines.router import router as deadlines_router
    from app.modules.documents.router import router as documents_router
    from app.modules.firm.router import router as firm_router
    from app.modules.identity.router import router as identity_router
    from app.modules.income_report.router import router as income_report_router
    from app.modules.invoicing.router import router as invoicing_router
    from app.modules.payments.router import router as payments_router
    from app.modules.payroll.router import router as payroll_router
    from app.modules.purchases.router import router as purchases_router
    from app.modules.rbac.router import router as rbac_router
    from app.modules.reports.router import router as reports_router
    from app.modules.stores.router import router as stores_router
    from app.modules.submissions.router import router as submissions_router
    from app.modules.vat.router import router as vat_router
    from app.modules.vat_refund.router import router as vat_refund_router

    prefix = settings.API_V1_PREFIX
    app.include_router(health_router, prefix=prefix)
    app.include_router(identity_router, prefix=prefix)
    app.include_router(companies_router, prefix=prefix)
    app.include_router(members_router, prefix=prefix)
    app.include_router(rbac_router, prefix=prefix)
    app.include_router(accounting_router, prefix=prefix)
    app.include_router(vat_router, prefix=prefix)
    app.include_router(vat_refund_router, prefix=prefix)
    app.include_router(reports_router, prefix=prefix)
    app.include_router(income_report_router, prefix=prefix)
    app.include_router(counterparties_router, prefix=prefix)
    app.include_router(documents_router, prefix=prefix)
    app.include_router(ai_router, prefix=prefix)
    app.include_router(banking_router, prefix=prefix)
    app.include_router(assets_router, prefix=prefix)
    app.include_router(audit_router, prefix=prefix)
    app.include_router(invoicing_router, prefix=prefix)
    app.include_router(payments_router, prefix=prefix)
    app.include_router(purchases_router, prefix=prefix)
    app.include_router(stores_router, prefix=prefix)
    app.include_router(submissions_router, prefix=prefix)
    app.include_router(deadlines_router, prefix=prefix)
    app.include_router(payroll_router, prefix=prefix)
    app.include_router(firm_router, prefix=prefix)


app = create_app()
