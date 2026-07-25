"""Конфигурация на приложението (12-factor, чрез environment / .env)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    PROJECT_NAME: str = "AI Finance OS"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "local"

    # База данни: SQLite по подразбиране (локален dev), PostgreSQL в production.
    DATABASE_URL: str = "sqlite:///./ai_finance_os.db"
    # В dev създаваме таблиците автоматично; в prod това е False и се ползва Alembic.
    AUTO_CREATE_TABLES: bool = True

    # Сигурност / JWT
    SECRET_KEY: str = "dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12  # 12 часа

    # Счетоводни настройки по подразбиране за нова компания
    DEFAULT_BASE_CURRENCY: str = "EUR"
    DEFAULT_COUNTRY: str = "BG"

    # CORS (за web frontend по-късно)
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # AI (Anthropic). Ключът се чете от ANTHROPIC_API_KEY в средата.
    ANTHROPIC_API_KEY: str = ""
    AI_MODEL: str = "claude-opus-5"
    AI_MAX_TOKENS: int = 8000
    # auto → anthropic ако има ключ, иначе stub (детерминиран, без мрежа — за dev/тестове).
    AI_PROVIDER: str = "auto"

    # ---- Авто-осчетоводяване на разпознати документи ----
    # Ако е True, документ с достатъчна увереност се осчетоводява автоматично
    # (без ръчно потвърждение). По подразбиране е изключено — AI само предлага.
    AUTO_POST_DOCUMENTS: bool = False
    AUTO_POST_MIN_CONFIDENCE: float = 0.80

    # PDF: път към Unicode TTF шрифт (празно → авто-намиране DejaVu/Arial).
    PDF_FONT_PATH: str = ""

    # ---- Интеграции с магазини (App Store / Google Play) ----
    # auto → реален конектор ако има credentials, иначе stub (детерминиран, за dev/тестове).
    STORE_PROVIDER: str = "auto"
    # Apple App Store Connect API (JWT ES256): частен ключ .p8 + идентификатори.
    APPLE_ISSUER_ID: str = ""
    APPLE_KEY_ID: str = ""
    APPLE_PRIVATE_KEY_PATH: str = ""   # път до AuthKey_XXXX.p8
    APPLE_VENDOR_NUMBER: str = ""      # номер на доставчика (за Sales Reports)
    # Google Play: финансовите отчети се експортират в Google Cloud Storage bucket.
    GOOGLE_PLAY_BUCKET: str = ""       # напр. pubsite_prod_..._<developer id>
    GOOGLE_APPLICATION_CREDENTIALS: str = ""  # път до service account JSON

    @property
    def resolved_store_provider(self) -> str:
        if self.STORE_PROVIDER != "auto":
            return self.STORE_PROVIDER
        has_apple = bool(self.APPLE_ISSUER_ID and self.APPLE_KEY_ID and self.APPLE_PRIVATE_KEY_PATH)
        has_google = bool(self.GOOGLE_PLAY_BUCKET and self.GOOGLE_APPLICATION_CREDENTIALS)
        return "live" if (has_apple or has_google) else "stub"

    # Съхранение на документи
    DOCUMENT_STORAGE_DIR: str = "./storage/documents"
    MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024  # 25 MB
    ALLOWED_CONTENT_TYPES: list[str] = [
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/heic",
        "image/webp",
        "image/tiff",
    ]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def resolved_ai_provider(self) -> str:
        if self.AI_PROVIDER == "auto":
            return "anthropic" if self.ANTHROPIC_API_KEY else "stub"
        return self.AI_PROVIDER


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
