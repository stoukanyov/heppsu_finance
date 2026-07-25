"""Съхранение на файлове на документи във файловата система.

Имената за съхранение се генерират от UUID (никога от потребителското име на файла),
което предотвратява path traversal и колизии. Оригиналното име се пази само като метаданни.
"""
import uuid
from pathlib import Path

from app.core.config import settings

_SAFE_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".webp", ".tif", ".tiff"}


def _base() -> Path:
    return Path(settings.DOCUMENT_STORAGE_DIR)


def save_file(company_id: uuid.UUID, original_filename: str, content: bytes) -> str:
    """Записва съдържанието и връща относителния път за съхранение."""
    ext = Path(original_filename).suffix.lower()
    if ext not in _SAFE_EXT:
        ext = ""
    rel_path = f"{company_id}/{uuid.uuid4().hex}{ext}"
    dest = _base() / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return rel_path


def read_file(storage_path: str) -> bytes:
    return (_base() / storage_path).read_bytes()
