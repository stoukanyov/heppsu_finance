"""LLM клиент за AI модула — абстракция над Anthropic API.

Две имплементации:
- AnthropicLLMClient — реален достъп до Claude (модел по подразбиране claude-opus-5),
  ползван, когато има ANTHROPIC_API_KEY.
- StubLLMClient — детерминиран, без мрежа; ползван в тестове и dev без ключ.

Структурираният изход се получава чрез принудително извикване на инструмент
(tool_choice) — устойчиво между версии на SDK. Ключът се чете от средата; кодът
никога не го логва и не го връща.
"""
from __future__ import annotations

import base64
from typing import Protocol

from app.core.config import settings

# ---------- JSON схеми за структурирания изход ----------
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "object",
            "properties": {
                "issuer": {"type": ["string", "null"]},
                "issuer_eik": {"type": ["string", "null"]},
                "issuer_vat_number": {"type": ["string", "null"]},
                "recipient": {"type": ["string", "null"]},
                "document_type": {"type": ["string", "null"]},
                "document_number": {"type": ["string", "null"]},
                "document_date": {"type": ["string", "null"]},
                "due_date": {"type": ["string", "null"]},
                "currency": {"type": ["string", "null"]},
                "tax_base": {"type": ["number", "null"]},
                "vat_rate": {"type": ["number", "null"]},
                "vat_amount": {"type": ["number", "null"]},
                "total": {"type": ["number", "null"]},
                "iban": {"type": ["string", "null"]},
            },
        },
        "field_confidence": {"type": "object"},
        "overall_confidence": {"type": "number"},
        "notes": {"type": ["string", "null"]},
    },
    "required": ["fields", "overall_confidence"],
}

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "explanation": {"type": "string"},
        "recommendations": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["summary", "explanation", "recommendations", "confidence"],
}

EXPENSE_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        # Счетоводно третиране
        "account_code": {"type": "string"},          # сметка от подадения сметкоплан
        "account_rationale": {"type": "string"},
        # Данъчно третиране по ЗКПО
        "is_deductible": {"type": "boolean"},        # признат разход за данъчни цели
        "deductible_ratio": {"type": ["number", "null"]},  # 0..1 при частично признаване
        "tax_rationale": {"type": "string"},
        # Право на данъчен кредит по ЗДДС
        "vat_credit": {
            "type": "string",
            "enum": ["FULL", "PARTIAL", "NONE", "UNKNOWN"],
        },
        "vat_rationale": {"type": "string"},
        "expense_category": {"type": "string"},      # човешко описание, напр. „гориво", „наем"
        "confidence": {"type": "number"},            # 0..1
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "account_code", "is_deductible", "vat_credit",
        "tax_rationale", "confidence",
    ],
}

_EXPENSE_SYSTEM = (
    "Ти си главен счетоводител и данъчен експерт по българското законодателство "
    "(ЗКПО, ЗДДС, Закон за счетоводството, НСС). Класифицирай разходен документ:\n"
    "1) Избери НАЙ-ПОДХОДЯЩАТА сметка САМО от подадения сметкоплан (върни точния код).\n"
    "2) Реши дали разходът е ДАНЪЧНО ПРИЗНАТ по ЗКПО. Типични НЕпризнати или ограничени: "
    "разходи, несвързани с дейността; представителни разходи (данък върху разходите по чл. 204 ЗКПО); "
    "дарения без основание; липси и брак без документ; глоби, санкции и лихви за просрочени публични "
    "задължения; разходи без документална обоснованост по чл. 10 ЗКПО; лични разходи на собственика; "
    "разходи за лек автомобил, използван за управленска дейност (ограничения по ЗДДС/ЗКПО).\n"
    "3) Реши за правото на ДАНЪЧЕН КРЕДИТ по ЗДДС: NONE при липса на фактура с ДДС номер, "
    "касова бележка без фактура, представителни разходи, лек автомобил и свързани разходи "
    "(чл. 70 ЗДДС), освободени доставки; FULL при обичайни стопански разходи с редовна фактура.\n"
    "ВАЖНО: не измисляй сметки, които не са в списъка. Ако данните са недостатъчни, дай ниска "
    "увереност и добави предупреждение. Обосновките пиши на български, кратко и с позоваване на "
    "разпоредбата, когато е приложимо. Ти само предлагаш — човек потвърждава."
)

_EXTRACT_SYSTEM = (
    "Ти си експерт по обработка на български счетоводни документи (фактури, известия). "
    "Извлечи полетата от документа възможно най-точно. Не измисляй стойности: ако поле "
    "липсва или не си сигурен, върни null и ниска увереност за него. Дай confidence 0..1 "
    "за всяко поле и обща увереност. Датите форматирай като YYYY-MM-DD."
)
_CFO_SYSTEM = (
    "Ти си AI финансов директор (CFO) на българска фирма с базова валута EUR. "
    "Анализирай САМО предоставените данни — не измисляй числа и не представяй предположения "
    "като факти. Посочвай несигурност и допускания. Отговаряй на български, кратко и по същество. "
    "Ти само съветваш — не осчетоводяваш, не подаваш декларации и не извършваш плащания."
)


class LLMClient(Protocol):
    def extract_document(self, content: bytes, media_type: str, filename: str) -> dict: ...
    def financial_analysis(self, context: dict, question: str | None) -> dict: ...
    def classify_expense(self, context: dict) -> dict: ...


class AnthropicLLMClient:
    def __init__(self, api_key: str, model: str, max_tokens: int):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def _structured(self, system: str, content: list, schema: dict) -> dict:
        tool = {"name": "record", "description": "Запиши резултата.", "input_schema": schema}
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": "record"},
            messages=[{"role": "user", "content": content}],
        )
        for block in resp.content:
            if block.type == "tool_use":
                return dict(block.input)
        return {}

    def extract_document(self, content: bytes, media_type: str, filename: str) -> dict:
        b64 = base64.standard_b64encode(content).decode("ascii")
        if media_type == "application/pdf":
            source = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
        elif media_type.startswith("image/"):
            source = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}
        else:
            raise ValueError(f"Неподдържан тип за OCR: {media_type}")
        prompt = f"Извлечи данните от този документ ({filename})."
        return self._structured(_EXTRACT_SYSTEM, [source, {"type": "text", "text": prompt}], EXTRACTION_SCHEMA)

    def financial_analysis(self, context: dict, question: str | None) -> dict:
        import json

        q = question or "Направи кратък преглед на финансовото състояние и препоръчай действия."
        user = f"Финансови данни (JSON):\n{json.dumps(context, ensure_ascii=False, default=str)}\n\nВъпрос: {q}"
        return self._structured(_CFO_SYSTEM, [{"type": "text", "text": user}], ANALYSIS_SCHEMA)

    def classify_expense(self, context: dict) -> dict:
        import json

        user = (
            "Класифицирай следния разходен документ на българска фирма.\n\n"
            f"Данни (JSON):\n{json.dumps(context, ensure_ascii=False, default=str)}"
        )
        return self._structured(
            _EXPENSE_SYSTEM, [{"type": "text", "text": user}], EXPENSE_CLASSIFICATION_SCHEMA
        )


class StubLLMClient:
    """Детерминиран клиент за dev/тестове — без мрежа."""

    def extract_document(self, content: bytes, media_type: str, filename: str) -> dict:
        return {
            "fields": {
                "issuer": "Примерен Доставчик ЕООД",
                "issuer_eik": "203000000",
                "issuer_vat_number": "BG203000000",
                "recipient": None,
                "document_type": "Фактура",
                "document_number": filename.rsplit(".", 1)[0][:20] or "F-0001",
                "document_date": "2026-07-15",
                "due_date": None,
                "currency": "EUR",
                "tax_base": 100.00,
                "vat_rate": 20.0,
                "vat_amount": 20.00,
                "total": 120.00,
                "iban": None,
            },
            "field_confidence": {"document_number": 0.9, "total": 0.85, "vat_amount": 0.8},
            "overall_confidence": 0.62,
            "notes": "Разпознато от stub клиент (без реален OCR).",
        }

    def financial_analysis(self, context: dict, question: str | None) -> dict:
        cash = context.get("cash", 0)
        profit = context.get("profit", 0)
        return {
            "summary": f"Наличности {cash} {context.get('currency', 'EUR')}; резултат за периода {profit}.",
            "explanation": "Детерминиран отговор от stub клиент — реалният анализ изисква Anthropic API ключ.",
            "recommendations": ["Свържи Anthropic API ключ, за да активираш реалния AI CFO анализ."],
            "risks": [],
            "assumptions": ["Данните са агрегирани от оборотната ведомост."],
            "confidence": "medium",
        }

    def classify_expense(self, context: dict) -> dict:
        """Детерминирана класификация по ключови думи — огледало на реалните правила.

        Реалният AI дава нюансирана обосновка; stub-ът покрива най-честите случаи,
        за да са възпроизводими тестовете и demo без API ключ.
        """
        text = " ".join(
            str(context.get(k) or "")
            for k in ("supplier_name", "document_type", "notes", "description", "expense_hint")
        ).lower()
        if context.get("is_receipt"):
            text += " касова бележка"
        available = {a.get("code") for a in context.get("available_accounts", []) if a.get("code")}

        def pick(code: str, fallback: str = "602") -> str:
            return code if code in available or not available else fallback

        # Непризнати / ограничени разходи по ЗКПО и без данъчен кредит по чл. 70 ЗДДС.
        if any(w in text for w in ("глоба", "санкц", "лихва за просроч", "неустойк")):
            return {
                "account_code": pick("609"),
                "account_rationale": "Глоби и санкции се отчитат като други разходи.",
                "is_deductible": False, "deductible_ratio": 0.0,
                "tax_rationale": "Разходът не се признава за данъчни цели (глоби, санкции и лихви за просрочени публични задължения — чл. 26 ЗКПО).",
                "vat_credit": "NONE",
                "vat_rationale": "Няма право на данъчен кредит.",
                "expense_category": "глоби и санкции",
                "confidence": 0.9, "warnings": [],
            }
        if any(w in text for w in ("представит", "почерпк", "банкет", "коктейл")):
            return {
                "account_code": pick("609"),
                "account_rationale": "Представителни разходи — други разходи.",
                "is_deductible": False, "deductible_ratio": 0.0,
                "tax_rationale": "Представителните разходи се облагат с данък върху разходите (чл. 204, ал. 1, т. 1 ЗКПО) и не намаляват данъчния резултат.",
                "vat_credit": "NONE",
                "vat_rationale": "Няма право на данъчен кредит по чл. 70, ал. 1, т. 3 ЗДДС.",
                "expense_category": "представителни разходи",
                "confidence": 0.85, "warnings": ["Провери дали е начислен данък върху разходите."],
            }
        if any(w in text for w in ("гориво", "бензин", "дизел", "shell", "omv", "лукойл", "petrol")):
            return {
                "account_code": pick("601"),
                "account_rationale": "Горивата се отчитат като разходи за материали.",
                "is_deductible": True, "deductible_ratio": 1.0,
                "tax_rationale": "Признат разход при документална обоснованост и връзка с дейността (чл. 10 ЗКПО); при лек автомобил за управленска дейност се прилагат ограничения.",
                "vat_credit": "FULL",
                "vat_rationale": "Пълен данъчен кредит, освен ако автомобилът не е лек по смисъла на чл. 70, ал. 1, т. 4-5 ЗДДС.",
                "expense_category": "гориво",
                "confidence": 0.75,
                "warnings": ["Уточни дали автомобилът е лек — влияе на данъчния кредит."],
            }
        if any(w in text for w in ("наем", "rent", "lease")):
            return {
                "account_code": pick("602"),
                "account_rationale": "Наемът е разход за външни услуги.",
                "is_deductible": True, "deductible_ratio": 1.0,
                "tax_rationale": "Признат разход, свързан с дейността.",
                "vat_credit": "FULL",
                "vat_rationale": "Пълен данъчен кредит при редовна фактура.",
                "expense_category": "наем",
                "confidence": 0.85, "warnings": [],
            }
        if "касова бележка" in text or "receipt" in text:
            return {
                "account_code": pick("602"),
                "account_rationale": "Разход за външни услуги (по подразбиране).",
                "is_deductible": True, "deductible_ratio": 1.0,
                "tax_rationale": "Признат при документална обоснованост и връзка с дейността.",
                "vat_credit": "NONE",
                "vat_rationale": "Касова бележка без фактура не дава право на данъчен кредит (чл. 71 ЗДДС).",
                "expense_category": "дребен разход",
                "confidence": 0.7,
                "warnings": ["Липсва фактура — няма право на данъчен кредит."],
            }
        return {
            "account_code": pick("602"),
            "account_rationale": "По подразбиране — разходи за външни услуги.",
            "is_deductible": True, "deductible_ratio": 1.0,
            "tax_rationale": "Приема се за признат разход, свързан с дейността; изисква преглед.",
            "vat_credit": "FULL",
            "vat_rationale": "Пълен данъчен кредит при редовна фактура с ДДС номер.",
            "expense_category": "общ разход",
            "confidence": 0.55,
            "warnings": ["Класификацията е по подразбиране (stub) — потвърди ръчно."],
        }


def get_llm_client() -> LLMClient:
    if settings.resolved_ai_provider == "anthropic":
        return AnthropicLLMClient(settings.ANTHROPIC_API_KEY, settings.AI_MODEL, settings.AI_MAX_TOKENS)
    return StubLLMClient()
