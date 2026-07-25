"""Каталог на правата (permissions) и предефинираните роли.

Моделът е гъвкав: правото е низ `ресурс.действие`, ролята е набор от права, а всяка
компания може да си дефинира собствени роли. Предефинираните роли са шаблони, които
покриват типичните участници в счетоводния процес на българска фирма.

Отделно от правата, всяка роля носи флаг **може ли да ползва мобилното приложение** —
мобилният достъп е решение на администратора, а не следствие от правата.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------- права
# Групите служат само за подредба в администраторския екран.
PERMISSIONS: dict[str, list[tuple[str, str]]] = {
    "Счетоводство": [
        ("accounting.view", "Преглед на сметкоплан, операции и журнали"),
        ("accounting.manage_chart", "Управление на сметкоплана и фискалните периоди"),
        ("accounting.create_entry", "Създаване на счетоводни операции (чернови)"),
        ("accounting.post_entry", "Осчетоводяване и сторниране на операции"),
        ("accounting.close_period", "Приключване на счетоводен период"),
    ],
    "Продажби и покупки": [
        ("invoices.view", "Преглед на издадени фактури"),
        ("invoices.create", "Създаване на фактури (чернови)"),
        ("invoices.issue", "Издаване и анулиране на фактури"),
        ("purchases.view", "Преглед на получени фактури"),
        ("purchases.create", "Въвеждане на покупки"),
        ("purchases.post", "Осчетоводяване на покупки"),
        ("counterparties.view", "Преглед на контрагенти"),
        ("counterparties.manage", "Създаване и редакция на контрагенти"),
    ],
    "Банки и плащания": [
        ("banking.view", "Преглед на банкови сметки и движения"),
        ("banking.import", "Импорт на банкови извлечения"),
        ("banking.reconcile", "Съпоставяне на движения"),
        ("payments.view", "Преглед на плащания"),
        ("payments.prepare", "Подготвяне на платежни нареждания"),
        ("payments.approve", "Одобряване на плащания (maker-checker)"),
    ],
    "Данъци": [
        ("vat.view", "Преглед на ДДС регистри и декларация"),
        ("vat.manage", "Управление на ДДС кодове и записи"),
        ("vat.close_period", "Приключване на ДДС период"),
        ("vat.refund_manage", "Управление на процедури по възстановяване"),
        ("submissions.prepare", "Подготвяне на пакети за НАП"),
        ("submissions.record", "Отбелязване на подаване и импорт на разписки"),
    ],
    "Документи": [
        ("documents.view", "Преглед на документи"),
        ("documents.upload", "Качване и сканиране на документи"),
        ("documents.approve", "Одобряване и осчетоводяване на документи"),
        ("documents.delete", "Анулиране на документи"),
    ],
    "Отчети и анализи": [
        ("reports.view", "Преглед на финансови отчети"),
        ("reports.export", "Експорт на отчети"),
        ("ai.use", "Използване на AI анализи и AI CFO"),
        ("stores.view", "Преглед на продажби от App Store / Google Play"),
        ("stores.sync", "Синхронизиране на магазините"),
    ],
    "Администрация": [
        ("company.view", "Преглед на реквизитите на дружеството"),
        ("company.manage", "Редакция на реквизитите на дружеството"),
        ("team.view", "Преглед на екипа"),
        ("team.manage", "Управление на екипа (добавяне и премахване)"),
        ("roles.manage", "Управление на роли и права"),
        ("audit.view", "Преглед на одитния журнал"),
        ("assets.view", "Преглед на дълготрайни активи"),
        ("assets.manage", "Управление на активи и амортизации"),
    ],
}

ALL_PERMISSIONS: list[str] = [code for group in PERMISSIONS.values() for code, _ in group]
PERMISSION_LABELS: dict[str, str] = {
    code: label for group in PERMISSIONS.values() for code, label in group
}

# Специално право: пълен достъп. Носителят му минава всяка проверка.
WILDCARD = "*"


def expand(permissions: list[str]) -> set[str]:
    """Разгъва набор права; `*` дава всички."""
    if WILDCARD in permissions:
        return set(ALL_PERMISSIONS)
    return set(permissions)


def _only(*prefixes: str) -> list[str]:
    """Всички права, започващи с даден префикс — за удобство при шаблоните."""
    return [p for p in ALL_PERMISSIONS if p.startswith(prefixes)]


@dataclass(frozen=True)
class RoleTemplate:
    """Предефинирана роля (шаблон)."""

    code: str
    name: str
    description: str
    permissions: list[str] = field(default_factory=list)
    can_use_mobile: bool = False
    is_admin: bool = False   # може да управлява роли и екип


# ---------------------------------------------------------------- предефинирани роли
ROLE_TEMPLATES: list[RoleTemplate] = [
    RoleTemplate(
        code="MANAGER",
        name="Управител",
        description="Пълни права върху всичко в дружеството.",
        permissions=[WILDCARD],
        can_use_mobile=True,
        is_admin=True,
    ),
    RoleTemplate(
        code="CHIEF_ACCOUNTANT",
        name="Главен счетоводител",
        description=(
            "Пълни счетоводни и данъчни права, включително приключване на периоди и "
            "подготовка на пакети за НАП. Без управление на роли."
        ),
        permissions=[
            *_only("accounting.", "vat.", "invoices.", "purchases.", "counterparties.",
                   "banking.", "documents.", "reports.", "assets.", "submissions."),
            "payments.view", "payments.approve", "ai.use", "company.view", "team.view", "audit.view",
        ],
        can_use_mobile=True,
    ),
    RoleTemplate(
        code="ACCOUNTANT",
        name="Счетоводител",
        description=(
            "Оперативно счетоводство: въвежда и осчетоводява документи, води ДДС "
            "регистрите. Не приключва периоди и не одобрява плащания."
        ),
        permissions=[
            "accounting.view", "accounting.create_entry", "accounting.post_entry",
            "invoices.view", "invoices.create", "invoices.issue",
            "purchases.view", "purchases.create", "purchases.post",
            "counterparties.view", "counterparties.manage",
            "banking.view", "banking.import", "banking.reconcile",
            "vat.view", "vat.manage",
            "documents.view", "documents.upload", "documents.approve",
            "reports.view", "reports.export", "assets.view", "ai.use", "company.view",
        ],
        can_use_mobile=True,
    ),
    RoleTemplate(
        code="CFO",
        name="Финансов директор",
        description="Финансов контрол: одобрява плащания, вижда всички отчети и анализи.",
        permissions=[
            "accounting.view", "invoices.view", "purchases.view", "counterparties.view",
            "banking.view", "banking.reconcile",
            "payments.view", "payments.prepare", "payments.approve",
            "vat.view", "vat.refund_manage", "documents.view", "documents.approve",
            "reports.view", "reports.export", "ai.use", "stores.view", "stores.sync",
            "company.view", "team.view", "audit.view", "assets.view",
        ],
        can_use_mobile=True,
    ),
    RoleTemplate(
        code="EXTERNAL_ACCOUNTANT",
        name="Външна счетоводна къща",
        description=(
            "Пълни счетоводни права за обслужващо счетоводно предприятие, без достъп до "
            "плащания и без управление на екипа."
        ),
        permissions=[
            *_only("accounting.", "vat.", "purchases.", "documents.", "submissions."),
            "invoices.view", "counterparties.view", "counterparties.manage",
            "banking.view", "banking.import", "banking.reconcile",
            "reports.view", "reports.export", "assets.view", "assets.manage", "company.view",
        ],
        can_use_mobile=True,
    ),
    RoleTemplate(
        code="EMPLOYEE",
        name="Служител",
        description=(
            "Само внася разходни документи от мобилното приложение (снимка на фактура "
            "или касова бележка). Не вижда счетоводството."
        ),
        permissions=["documents.view", "documents.upload"],
        can_use_mobile=True,
    ),
    RoleTemplate(
        code="APPROVER",
        name="Одобряващ",
        description="Одобрява разходни документи и плащания от мобилното приложение.",
        permissions=[
            "documents.view", "documents.upload", "documents.approve",
            "payments.view", "payments.approve", "reports.view",
        ],
        can_use_mobile=True,
    ),
    RoleTemplate(
        code="AUDITOR",
        name="Одитор",
        description="Само за преглед: вижда всичко, не променя нищо.",
        permissions=[
            "accounting.view", "invoices.view", "purchases.view", "counterparties.view",
            "banking.view", "payments.view", "vat.view", "documents.view",
            "reports.view", "reports.export", "audit.view", "assets.view", "company.view",
        ],
        can_use_mobile=False,
    ),
    RoleTemplate(
        code="TAX_CONSULTANT",
        name="Данъчен консултант",
        description="Данъчен преглед и консултации; подготвя декларации, но не осчетоводява.",
        permissions=[
            "accounting.view", "vat.view", "vat.refund_manage", "submissions.prepare",
            "invoices.view", "purchases.view", "documents.view",
            "reports.view", "reports.export", "ai.use", "company.view",
        ],
        can_use_mobile=False,
    ),
    RoleTemplate(
        code="READ_ONLY",
        name="Само за четене",
        description="Минимален достъп: преглед на отчети и документи.",
        permissions=["reports.view", "documents.view", "company.view"],
        can_use_mobile=False,
    ),
]

ROLE_TEMPLATES_BY_CODE: dict[str, RoleTemplate] = {t.code: t for t in ROLE_TEMPLATES}
