"""Конфигурация на приложението (12-factor, чрез environment / .env)."""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class InsecureConfigurationError(RuntimeError):
    """Опасна конфигурация — приложението отказва да стартира (fail-fast)."""


# Стойността по подразбиране е удобна за dev, но е публична — в production е забранена.
DEFAULT_SECRET_KEY = "dev-secret-change-me"
# Под 32 байта ентропия HS256 ключът е податлив на офлайн brute force.
MIN_SECRET_KEY_BYTES = 32
# Среди, в които изискваме „истинска“ конфигурация.
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod", "staging"})
# Среди, в които подставени данни са забранени на всяка цена — дори при изрично
# `STORE_PROVIDER=stub`, `BANK_PROVIDER=stub` или `AI_PROVIDER=stub`. Важи за
# ВСЕКИ доставчик, не само за магазините: измислените числа изглеждат като
# счетоводни данни, а в production до тях няма кой да сложи етикет „демо“.
# „staging“ НЕ е тук нарочно: демо средата е staging и живее от показни данни.
STUB_FORBIDDEN_ENVIRONMENTS = frozenset({"production", "prod"})
# Подписваме със споделен таен ключ → само симетрични алгоритми. „none“ никога.
ALLOWED_JWT_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})
# Препоръчителен живот на access токена, след като всички клиенти ползват /auth/refresh.
# Не е стойност по подразбиране — виж коментара при ACCESS_TOKEN_EXPIRE_MINUTES.
RECOMMENDED_ACCESS_TOKEN_MINUTES = 15


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
    SECRET_KEY: str = DEFAULT_SECRET_KEY
    JWT_ALGORITHM: str = "HS256"
    # Access токенът е самодостатъчен (JWT) и НЕ може да бъде отменен, докато не изтече —
    # затова стойността е кратка. И двата клиента вече ротират: мобилният през
    # `ApiClient`, уебът през `ensureFreshToken` в `app/web/index.html`.
    #
    # Практическата разлика: при компрометиран токен прозорецът е 15 минути вместо
    # 12 часа, а отмяната на refresh токена (изход, кражба) става веднага.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = RECOMMENDED_ACCESS_TOKEN_MINUTES

    # ---- Refresh токени (ротация с откриване на преизползване) ----
    # Непрозрачен случаен низ, пазен в базата само като SHA-256 хеш. Дълъг живот, но
    # отменяем: при logout, при ротация и масово — при кражба.
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ---- Двуфакторна автентикация (TOTP) ----
    # Междинният токен между паролата и кода. Кратък нарочно: той е доказателство,
    # че паролата е била вярна, и не бива да се разхожда дълго. 5 минути стигат за
    # отваряне на автентикатора, дори при търсене на телефона.
    MFA_CHALLENGE_TTL_SECONDS: int = 300
    # Колко резервни кода се издават при включване. Показват се ВЕДНЪЖ.
    TOTP_RECOVERY_CODE_COUNT: int = 10
    # Приемани стъпки назад и напред (часовата разлика на телефона). 1 = ±30 секунди.
    TOTP_WINDOW_STEPS: int = 1
    # Издателят, който автентикаторът показва над кода.
    TOTP_ISSUER: str = "AI Finance OS"

    # ---- Ограничаване на опитите (brute force защита) ----
    # Плъзгащ прозорец в базата (обща за всички процеси). Изключваемо (тестове, отладка).
    RATE_LIMIT_ENABLED: bool = True
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 5          # неуспешни опита от едно IP срещу един акаунт...
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 900  # ...в рамките на 15 минути
    # Срещу един акаунт от ВСИЧКИ IP-та — спира разпределеното налучкване, при което
    # всеки нов адрес иначе получава пълна нова квота. Прагът е висок нарочно: по-нисък
    # би позволил на всеки, който знае чужд имейл, да го държи заключен.
    LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS: int = 20
    # От едно IP срещу ВСИЧКИ акаунти — спира password spraying (една вероятна парола
    # срещу хиляди имейла), който при ключ „IP+акаунт" не се брои никъде.
    LOGIN_RATE_LIMIT_IP_ATTEMPTS: int = 30
    # Зад reverse proxy (Caddy/nginx) реалният клиентски IP идва в X-Real-IP.
    # Включвай САМО ако приложението не е директно достъпно от интернет — иначе
    # header-ите са подправяеми и ограничението се заобикаля тривиално.
    RATE_LIMIT_TRUST_PROXY_HEADER: bool = False

    # Счетоводни настройки по подразбиране за нова компания
    DEFAULT_BASE_CURRENCY: str = "EUR"
    DEFAULT_COUNTRY: str = "BG"

    # CORS (за web frontend по-късно)
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # AI (Anthropic). Ключът се чете от ANTHROPIC_API_KEY в средата.
    ANTHROPIC_API_KEY: str = ""
    AI_MODEL: str = "claude-opus-5"
    AI_MAX_TOKENS: int = 8000
    # auto → anthropic ако има ключ, иначе „off“. Подставените отговори искат
    # изрично AI_PROVIDER=stub и са забранени в production (виж ai_provider).
    AI_PROVIDER: str = "auto"

    # ---- Подаване към НАП ----
    # Днес е наличен само пакетът за ръчно подаване през портала (с КЕП).
    # При публикуване на официален API се сменя само тази настройка.
    NRA_SUBMISSION_PROVIDER: str = "NRA_PORTAL_PACKAGE"
    NRA_PORTAL_URL: str = "https://portal.nra.bg/"

    # ---- Възстановяване на ДДС (чл. 92 ЗДДС) ----
    # Минимален дял доставки с нулева ставка за ускорено възстановяване по ал. 3.
    VAT_ACCELERATED_ZERO_RATE_THRESHOLD: float = 0.30
    # Хипотезата за земеделски производители е с краен срок 31.12.2026 — конфигурируема.
    VAT_FARMER_SCHEME_ENABLED: bool = False
    VAT_FARMER_OWN_PRODUCE_THRESHOLD: float = 0.50
    VAT_FARMER_SCHEME_EXPIRES: str = "2026-12-31"
    # Срокове: подаване до 14-о число; възстановяване в 30 дни след приключване.
    VAT_SUBMISSION_DAY: int = 14
    VAT_REFUND_DEADLINE_DAYS: int = 30

    # ---- Maker-checker (принцип „четири очи“) ----
    # Глобална стойност по подразбиране за нови и за компании без изрична настройка.
    # Изключено: първият клиент е фирма с един човек и включването би я блокирало.
    # Всяка компания може да го включи за себе си (`companies.maker_checker_enabled`).
    MAKER_CHECKER_ENABLED: bool = False

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

    # ---- Банки (PSD2 / open banking) ----
    # Ключовете се четат само от средата (D-009).
    # auto → реалният доставчик ако има credentials, иначе „off“ (не stub).
    BANK_PROVIDER: str = "auto"
    GOCARDLESS_SECRET_ID: str = ""
    GOCARDLESS_SECRET_KEY: str = ""

    @property
    def apple_configured(self) -> bool:
        """App Store Connect: трите неща, без които няма подписан токен."""
        return bool(self.APPLE_ISSUER_ID and self.APPLE_KEY_ID and self.APPLE_PRIVATE_KEY_PATH)

    @property
    def google_play_configured(self) -> bool:
        """Google Play: кофата с отчетите и service account-ът, който я чете."""
        return bool(self.GOOGLE_PLAY_BUCKET and self.GOOGLE_APPLICATION_CREDENTIALS)

    def store_provider_for(self, platform: str) -> str:
        """Режимът за ЕДИН магазин: „live“, „stub“ или „off“.

        Беше една обща стойност за двата магазина и даваше „live“, щом е
        конфигуриран кой да е от двата — тоест синхронизирането на Google Play
        тръгваше към реалния конектор само защото Apple има ключ, и се чупеше в
        него. Режимът е на магазин, защото ключовете са на магазин.

        „off“ значи „няма ключове“ и НЕ е „покажи измислени числа“: `auto`
        никога не връща `stub`. Подставените данни искат изрично
        `STORE_PROVIDER=stub` (демо средата), защото на 26.10.2026 production
        носеше 1305 реда измислени продажби на приложения, които не съществуват,
        и те изглеждаха като счетоводни данни.
        """
        konfiguriran = {
            "APP_STORE": self.apple_configured,
            "GOOGLE_PLAY": self.google_play_configured,
        }.get(str(platform).upper(), False)
        return self._rezhim(self.STORE_PROVIDER, konfiguriran)

    @property
    def resolved_store_provider(self) -> str:
        """Общ режим за екрана: „live“, ако поне един магазин е свързан."""
        rezhimi = {self.store_provider_for(p) for p in ("APP_STORE", "GOOGLE_PLAY")}
        for rezhim in ("live", "stub", "off"):
            if rezhim in rezhimi:
                return rezhim
        return "off"

    # ---- Мобилен клиент ----
    # Версията, под която приложението спира да работи. Проверката е на сървъра,
    # за да може да се вдигне без ново издание в магазина — това е единственият
    # начин да се извади от употреба клиент с намерен пробив в сигурността.
    # Празно/„0.0.0“ = нищо не се блокира.
    MOBILE_MIN_SUPPORTED_VERSION: str = "0.0.0"
    # Последната публикувана версия — по-старите виждат ненатрапчива покана.
    MOBILE_LATEST_VERSION: str = ""
    MOBILE_IOS_STORE_URL: str = ""
    MOBILE_ANDROID_STORE_URL: str = ""
    # Обяснение, което се показва при блокиране (напр. „поправка в изчисляването на ДДС“).
    MOBILE_UPDATE_MESSAGE: str = ""

    # Приемане на отчети за сривове от мобилния клиент.
    CRASH_REPORTING_ENABLED: bool = True
    CRASH_REPORT_RATE_LIMIT: int = 20            # доклада...
    CRASH_REPORT_RATE_WINDOW_SECONDS: int = 3600  # ...на час от един IP

    # ---- Докладване от потребителя → Control Center (модул support) ----
    # Докладът винаги се записва в нашата база; препращането към Control Center
    # става само когато и двете стойности са попълнени. Празни (по подразбиране)
    # → `GET /support/config` казва `configured: false`, нищо не се праща навън,
    # докладите чакат в базата и тръгват, щом настройката се появи.
    # Пример: COCKPIT_URL=https://cockpit.heppsu.com (без /api/tickets — пътят е в кода).
    COCKPIT_URL: str = ""
    # Токенът на системата `aifos` / `aifos-preprod` в Control Center (`X-App-Token`).
    # Само от средата; не се логва и не се връща в отговор.
    COCKPIT_APP_TOKEN: str = ""
    # Фоновият цикъл, който препраща чакащите доклади. Изключва се в тестовете.
    SUPPORT_FORWARDER_ENABLED: bool = True
    SUPPORT_FORWARD_INTERVAL_SECONDS: int = 60
    SUPPORT_FORWARD_TIMEOUT_SECONDS: float = 10.0
    # Таван на изчакването между опитите (експоненциално: 1, 2, 4… минути до тук).
    SUPPORT_FORWARD_MAX_BACKOFF_SECONDS: int = 3600
    # Доклади от един потребител (и адрес) за прозореца. Същото като тавана на
    # Control Center на подател за час (`ticket_ip_hourly_limit` = 5): над него
    # тикетът и без това би чакал в опашката — по-честно е да кажем 429 веднага.
    SUPPORT_REPORT_RATE_LIMIT: int = 5
    SUPPORT_REPORT_RATE_WINDOW_SECONDS: int = 3600

    @property
    def support_forwarding_configured(self) -> bool:
        """Може ли да се препраща: адрес И токен, адресът по HTTPS извън локалната среда.

        Токенът по чист HTTP през интернет е токен на всеки по пътя — затова в
        production/staging адрес `http://` се смята за НЕнастроен, а не за
        „настроен, но опасен“.
        """
        url = self.COCKPIT_URL.strip()
        if not url or not self.COCKPIT_APP_TOKEN.strip():
            return False
        if url.startswith("https://"):
            return True
        return url.startswith("http://") and not self.is_production

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
    def gocardless_configured(self) -> bool:
        """Банковият доставчик: двата ключа, без които няма токен."""
        return bool(self.GOCARDLESS_SECRET_ID and self.GOCARDLESS_SECRET_KEY)

    @property
    def bank_provider(self) -> str:
        """Режимът за банките: „live“, „stub“ или „off“.

        Беше `live if available else stub`, тоест production без ключове
        предлагаше „УниКредит Булбанк (демо)“ и наливаше измислени движения по
        120,50 EUR в истинския дневник. „off“ значи „няма ключове“, а не
        „покажи измислени движения“.
        """
        return self._rezhim(self.BANK_PROVIDER, self.gocardless_configured)

    @property
    def ai_configured(self) -> bool:
        """AI: ключът за Anthropic. Чете се само от средата, никъде не се логва."""
        return bool(self.ANTHROPIC_API_KEY)

    @property
    def ai_provider(self) -> str:
        """Режимът за AI: „anthropic“, „stub“ или „off“.

        Подставеният клиент връща измислени стойности за данъчна основа, ДДС и
        сметка по ЗКПО. Етикетът „(stub)“ в бележката не стига: числата влизат
        в document_extractions и expense_classifications срещу истински
        документи. В production няма резервен вариант — има ясна грешка.
        """
        return self._rezhim(self.AI_PROVIDER, self.ai_configured, zhivo="anthropic")

    @property
    def resolved_ai_provider(self) -> str:
        """Старото име на `ai_provider`; пази съвместимост с извикващия код."""
        return self.ai_provider

    def _rezhim(self, izbran: str, konfiguriran: bool, zhivo: str = "live") -> str:
        """Общото правило за всеки доставчик: избраното, но без stub в production."""
        izbran = (izbran or "auto").strip().lower()
        if izbran == "stub":
            if self.ENVIRONMENT.strip().lower() in STUB_FORBIDDEN_ENVIRONMENTS:
                return "off"
            return "stub"
        if izbran == "off":
            # Изрично изключен доставчик си остава изключен, дори с налични ключове.
            return "off"
        if izbran in (zhivo, "live"):
            return zhivo
        return zhivo if konfiguriran else "off"

    @property
    def is_production(self) -> bool:
        """Производствена среда (production/prod/staging) — валидациите са строги."""
        return self.ENVIRONMENT.strip().lower() in PRODUCTION_ENVIRONMENTS

    # ------------------------------------------------------------------
    # Fail-fast валидации: изпълняват се при създаване на Settings, тоест при
    # импортиране на модула — приложението пада на старта, а не при първа заявка.
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _validate_security(self) -> "Settings":
        algorithm = self.JWT_ALGORITHM.strip().upper()
        if algorithm not in ALLOWED_JWT_ALGORITHMS:
            raise InsecureConfigurationError(
                f"Опасна конфигурация: JWT_ALGORITHM='{self.JWT_ALGORITHM}' не е разрешен.\n"
                f"Позволени са само {sorted(ALLOWED_JWT_ALGORITHMS)} — токените се подписват "
                "със споделен таен ключ (HMAC).\n"
                "Стойности като 'none' или асиметрични алгоритми биха позволили приемане на "
                "неподписани/чужди токени."
            )

        if not self.is_production:
            # dev/test: дефолтният ключ е удобен и безопасен (нищо реално не се пази).
            return self

        problem = _secret_key_problem(self.SECRET_KEY)
        if problem:
            raise InsecureConfigurationError(
                f"Опасна конфигурация: SECRET_KEY {problem} "
                f"(ENVIRONMENT='{self.ENVIRONMENT}').\n"
                "Приложението НЕ стартира, защото със знаен ключ всеки може да си подпише "
                "валиден JWT токен и да влезе като произволен потребител.\n\n"
                "Генерирай силен ключ:\n"
                "    openssl rand -hex 32\n\n"
                "и го подай през средата (.env / docker-compose):\n"
                "    SECRET_KEY=<генерираният низ>\n\n"
                "Виж docs/DEPLOY.md, раздел „4. Конфигурация (.env)“."
            )
        return self


def _secret_key_problem(secret_key: str) -> str | None:
    """Връща описание на проблема с ключа на български или None, ако е наред."""
    if not secret_key.strip():
        return "е празен"
    if secret_key == DEFAULT_SECRET_KEY:
        return f"е оставен на стойността по подразбиране ('{DEFAULT_SECRET_KEY}')"
    if len(secret_key.encode("utf-8")) < MIN_SECRET_KEY_BYTES:
        return (
            f"е твърде къс ({len(secret_key.encode('utf-8'))} байта, "
            f"минимум {MIN_SECRET_KEY_BYTES})"
        )
    return None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
