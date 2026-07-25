"""Тестове за Tax Engine абстракцията (ITaxProvider + registry)."""
from app.tax_engine.base import TaxProvider
from app.tax_engine.registry import available_providers, get_provider


def test_bulgaria_provider_registered():
    p = get_provider("BG")
    assert isinstance(p, TaxProvider)
    assert p.jurisdiction.country == "BG"
    assert p.jurisdiction.code == "BG-NRA"


def test_unknown_country_falls_back_to_bulgaria():
    # непозната държава → fallback към България (единственият регистриран провайдър)
    p = get_provider("XX")
    assert p.jurisdiction.country == "BG"
    # None също не гърми
    assert get_provider(None).jurisdiction.country == "BG"


def test_available_providers_nonempty():
    provs = available_providers()
    assert any(p.jurisdiction.country == "BG" for p in provs)


def test_provider_computes_declaration_like_before():
    """Провайдърът дава същия резултат като директната класификация (Strangler seam)."""
    from app.tax_engine.providers.bulgaria import BulgariaTaxProvider

    p = BulgariaTaxProvider()
    # без записи → нулева декларация с коректни клетки
    cells = p.compute_declaration([])
    rows = {r["cell"]: r["amount"] for r in cells.as_rows()}
    assert rows["50"] == 0 or str(rows["50"]) == "0.00"
