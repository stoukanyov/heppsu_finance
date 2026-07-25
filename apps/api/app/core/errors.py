"""Структурирани грешки за отказан достъп.

`detail` остава ЧЕТИМ НИЗ (както всички останали грешки в API-то), за да го показват
правилно и уеб, и мобилният клиент. Машинно четимите полета (`code`, `contact_admin`,
`required_permission`) идват отделно на горно ниво на отговора — новите клиенти могат да
реагират по код, старите просто показват съобщението.
"""
from __future__ import annotations

from fastapi import Request, status
from fastapi.responses import JSONResponse


class AccessDeniedError(Exception):
    """Отказан достъп: липсващо право, липсващ мобилен достъп или нужда от админ."""

    def __init__(
        self,
        message: str,
        code: str,
        *,
        required_permission: str | None = None,
        role: str | None = None,
        contact_admin: bool = True,
        status_code: int = status.HTTP_403_FORBIDDEN,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.required_permission = required_permission
        self.role = role
        self.contact_admin = contact_admin
        self.status_code = status_code


async def access_denied_handler(_request: Request, exc: AccessDeniedError) -> JSONResponse:
    body: dict = {
        "detail": exc.message,          # четимо съобщение — съвместимо с всички клиенти
        "code": exc.code,               # машинно четим код (напр. MOBILE_ACCESS_DENIED)
        "contact_admin": exc.contact_admin,
    }
    if exc.required_permission:
        body["required_permission"] = exc.required_permission
    if exc.role:
        body["role"] = exc.role
    return JSONResponse(status_code=exc.status_code, content=body)
