"""Централен импорт на всички модели.

Импортирането тук регистрира моделите в `Base.metadata`, за да работят
`create_all`, Alembic autogenerate и string-базираните relationship връзки.
Добавяй нови модули тук при създаването им.
"""
# noqa: F401 — импортите са заради страничния ефект на регистрацията.
from app.modules.accounting import models as accounting_models  # noqa: F401
from app.modules.ai import models as ai_models  # noqa: F401
from app.modules.assets import models as assets_models  # noqa: F401
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.banking import models as banking_models  # noqa: F401
from app.modules.companies import models as companies_models  # noqa: F401
from app.modules.counterparties import models as counterparties_models  # noqa: F401
from app.modules.documents import models as documents_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.invoicing import models as invoicing_models  # noqa: F401
from app.modules.mobile import models as mobile_models  # noqa: F401
from app.modules.payments import models as payments_models  # noqa: F401
from app.modules.purchases import models as purchases_models  # noqa: F401
from app.modules.rbac import models as rbac_models  # noqa: F401
from app.modules.stores import models as stores_models  # noqa: F401
from app.modules.submissions import models as submissions_models  # noqa: F401
from app.modules.vat import models as vat_models  # noqa: F401
from app.modules.vat_refund import models as vat_refund_models  # noqa: F401
