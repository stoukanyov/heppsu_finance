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


def get_llm_client() -> LLMClient:
    if settings.resolved_ai_provider == "anthropic":
        return AnthropicLLMClient(settings.ANTHROPIC_API_KEY, settings.AI_MODEL, settings.AI_MAX_TOKENS)
    return StubLLMClient()
