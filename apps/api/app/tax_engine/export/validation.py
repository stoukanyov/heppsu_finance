"""Валидация на изходните файлове преди подаване.

Досега експортите носеха уговорката „форматът следва публикуваните изисквания към
момента на писане“ (Q-006, Q-011). Уговорката е честна, но не е проверка. Тук е
механизмът, който я превръща в проверка:

* **XSD валидация** — файлът се сверява със схемата на данъчната администрация,
  когато схемата е налична в репото. Грешките се връщат с път в документа и ред,
  за да са полезни на човек, а не само на машина.
* **Структурни проверки** — правила, които не изискват схема: балансира ли дневникът,
  съвпадат ли контролните суми, попълнени ли са задължителните реквизити.
* **Проверка по дължина на полетата** — за форматираните текстови файлове на НАП.

Липсваща схема НЕ е мълчалив успех: докладът го казва изрично, заедно с пътя,
на който да се сложи файлът.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

ERROR = "ERROR"
WARNING = "WARNING"
INFO = "INFO"

_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


@dataclass(frozen=True)
class ValidationIssue:
    """Едно нарушение, локализирано максимално точно."""

    level: str
    message: str
    path: str | None = None      # XPath в документа или име на поле
    line: int | None = None
    source: str | None = None    # кой файл в пакета (POKUPKI.TXT и т.н.)

    def as_text(self) -> str:
        where = " · ".join(p for p in (self.source, self.path, f"ред {self.line}" if self.line else None) if p)
        return f"{self.message}" + (f" ({where})" if where else "")


@dataclass
class ValidationReport:
    """Резултатът от проверката на един изходен файл или пакет."""

    target: str                       # какво е проверявано, за човек
    schema_name: str | None = None
    schema_present: bool = False
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == WARNING]

    @property
    def ok(self) -> bool:
        """Няма грешки. Предупрежденията не спират подаването."""
        return not self.errors

    def add(self, level: str, message: str, **kwargs) -> None:
        self.issues.append(ValidationIssue(level=level, message=message, **kwargs))

    def extend(self, issues: list[ValidationIssue]) -> None:
        self.issues.extend(issues)

    def summary(self) -> str:
        if self.errors:
            return f"{len(self.errors)} грешки, {len(self.warnings)} предупреждения"
        if self.warnings:
            return f"Без грешки, {len(self.warnings)} предупреждения"
        return "Файлът е валиден"


# ==================================================================== XSD
class XsdSchema:
    """Обвивка около XSD схема, която може и да липсва.

    Схемите на НАП не се преразпространяват автоматично — файлът се слага ръчно в
    `app/tax_engine/export/schemas/`. Докато го няма, валидаторът не мълчи, а казва
    какво липсва и къде да се сложи.
    """

    def __init__(self, filename: str, name: str, *, directory: Path | None = None):
        self.filename = filename
        self.name = name
        self.path = (directory or _SCHEMA_DIR) / filename

    @property
    def available(self) -> bool:
        return self.path.is_file()

    @property
    def display_path(self) -> str:
        """Път за показване — относителен спрямо `app/`, за да не изтича структурата на сървъра."""
        try:
            root = Path(__file__).resolve().parents[2]      # .../app
            return str(self.path.relative_to(root.parent))
        except ValueError:
            return self.path.name

    @property
    def install_hint(self) -> str:
        return (
            f"Схемата „{self.name}“ не е инсталирана. Свали официалния XSD файл от НАП "
            f"и го сложи като {self.display_path}. Без схема файлът не може да се валидира "
            f"формално — проверени са само структурните правила."
        )

    def validate(self, xml: bytes) -> list[ValidationIssue]:
        """Валидира XML срещу схемата. Връща всички намерени грешки, не само първата."""
        if not self.available:
            return [ValidationIssue(level=WARNING, message=self.install_hint)]
        if importlib.util.find_spec("xmlschema") is None:
            return [
                ValidationIssue(
                    level=WARNING,
                    message=(
                        "Липсва пакетът `xmlschema` — XSD валидацията е пропусната. "
                        "Инсталирай зависимостите от requirements.txt."
                    ),
                )
            ]

        try:
            schema = _load_schema(str(self.path))
        except Exception as exc:  # повреден или непълен XSD
            return [
                ValidationIssue(
                    level=ERROR,
                    message=f"Схемата „{self.name}“ не може да се зареди: {exc}",
                    path=str(self.path),
                )
            ]

        issues: list[ValidationIssue] = []
        try:
            for err in schema.iter_errors(xml.decode("utf-8", errors="replace")):
                issues.append(
                    ValidationIssue(
                        level=ERROR,
                        message=_readable(err),
                        path=getattr(err, "path", None),
                        line=getattr(err, "sourceline", None),
                    )
                )
        except Exception as exc:  # непарсваем XML — схемата не стига дотам
            issues.append(
                ValidationIssue(level=ERROR, message=f"Файлът не е валиден XML: {exc}")
            )
        return issues


_SCHEMA_CACHE: dict[str, object] = {}


def _load_schema(path: str):
    """Зареждането на XSD е бавно — кешира се по път."""
    schema = _SCHEMA_CACHE.get(path)
    if schema is None:
        import xmlschema

        schema = xmlschema.XMLSchema(path)
        _SCHEMA_CACHE[path] = schema
    return schema


def _readable(err) -> str:
    """Превръща съобщението на валидатора в едноредово четимо изречение."""
    reason = getattr(err, "reason", None) or str(err)
    first = str(reason).strip().splitlines()[0]
    elem = getattr(err, "elem", None)
    tag = getattr(elem, "tag", None)
    if tag:
        tag = str(tag).rsplit("}", 1)[-1]
        return f"Елемент <{tag}>: {first}"
    return first


# ==================================================================== текстови файлове
@dataclass(frozen=True)
class FieldSpec:
    """Описание на едно поле във форматиран текстов файл на НАП.

    `width` е максималната дължина по спецификацията. `numeric` означава, че полето
    е парично/числово и се проверява за формат, а не за дължина на текст.
    """

    name: str
    width: int
    numeric: bool = False
    required: bool = False

    def check(self, value: str, *, source: str, line: int) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if self.required and not value.strip():
            issues.append(
                ValidationIssue(
                    level=ERROR,
                    message=f"Задължителното поле „{self.name}“ е празно",
                    path=self.name,
                    line=line,
                    source=source,
                )
            )
        if not self.numeric and len(value) > self.width:
            issues.append(
                ValidationIssue(
                    level=ERROR,
                    message=(
                        f"Поле „{self.name}“ е {len(value)} знака при максимум {self.width} "
                        f"— стойността ще бъде отрязана при подаване"
                    ),
                    path=self.name,
                    line=line,
                    source=source,
                )
            )
        if self.numeric and value.strip():
            try:
                float(value)
            except ValueError:
                issues.append(
                    ValidationIssue(
                        level=ERROR,
                        message=f"Поле „{self.name}“ не е число: {value!r}",
                        path=self.name,
                        line=line,
                        source=source,
                    )
                )
        return issues


def validate_delimited(
    content: str, specs: list[FieldSpec], *, source: str, delimiter: str = ";"
) -> list[ValidationIssue]:
    """Проверява всеки ред на разделен файл спрямо описанието на полетата."""
    issues: list[ValidationIssue] = []
    for line_no, row in enumerate(content.splitlines(), start=1):
        if not row.strip():
            continue
        values = row.split(delimiter)
        if len(values) != len(specs):
            issues.append(
                ValidationIssue(
                    level=ERROR,
                    message=(
                        f"Редът има {len(values)} полета вместо {len(specs)} по спецификацията"
                    ),
                    line=line_no,
                    source=source,
                )
            )
            continue
        for spec, value in zip(specs, values, strict=True):
            issues.extend(spec.check(value, source=source, line=line_no))
    return issues


def check_encoding(content: str, encoding: str, *, source: str) -> list[ValidationIssue]:
    """Проверява, че съдържанието се кодира без загуба в изисканата кодировка.

    Кирилицата минава в CP1251, но емоджи, тирета-дълги и латински разширени знаци —
    не. Мълчаливата подмяна с „?“ поврежда името на контрагента в подадения файл.
    """
    issues: list[ValidationIssue] = []
    for line_no, row in enumerate(content.splitlines(), start=1):
        try:
            row.encode(encoding)
        except UnicodeEncodeError as exc:
            bad = row[exc.start:exc.end]
            issues.append(
                ValidationIssue(
                    level=ERROR,
                    message=(
                        f"Знакът {bad!r} не може да се запише в кодировка {encoding.upper()} "
                        f"— замени го, преди да подадеш файла"
                    ),
                    line=line_no,
                    source=source,
                )
            )
    return issues
