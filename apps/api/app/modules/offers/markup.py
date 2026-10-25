"""Лека разметка за текста на офертата — един парсер за екрана и за PDF-а.

Знаците са като в Markdown, защото те вече се знаят и се пишат на ръка:

    # Заглавие          → заглавие от първо ниво
    ## Подзаглавие      → второ ниво
    ### Трето ниво      → трето ниво
    * точка от списък   → точка (булет)
    **получер**         → получер текст в реда
    [[позиции]]         → мястото, където застава таблицата с позициите

Празният ред разделя абзаците; последователните обикновени редове се сливат в
един абзац, за да се пренася текстът сам в PDF-а. Обратната наклонена черта
обезсилва следващия знак: `\\* това не е булет`.

**Защо тук, а не в браузъра:** предварителният преглед и PDF-ът трябва да
показват едно и също. Два парсера (JavaScript за екрана, Python за PDF-а) се
разминават тихо — затова екранът пита този и рисува върнатите блокове.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Знаците, които обратната наклонена черта обезсилва.
_ESCAPABLE = "*#[\\"

BlockKind = Literal["h1", "h2", "h3", "bullets", "paragraph", "items"]

#: Маркерът, който казва къде в текста застава таблицата с позициите.
ITEMS_MARKER = "[[позиции]]"
#: Приема се и латинският вариант — хората пишат и на двете.
ITEMS_MARKER_LATIN = "[[items]]"


@dataclass(frozen=True)
class Run:
    """Отрязък текст с еднакво оформление."""

    text: str
    bold: bool = False

    def as_dict(self) -> dict:
        return {"text": self.text, "bold": self.bold}


@dataclass
class Block:
    """Блок от документа: заглавие, абзац, списък или мястото на таблицата."""

    kind: BlockKind
    runs: list[Run] = field(default_factory=list)
    items: list[list[Run]] = field(default_factory=list)

    def as_dict(self) -> dict:
        out: dict = {"kind": self.kind}
        if self.kind in ("h1", "h2", "h3", "paragraph"):
            out["runs"] = [r.as_dict() for r in self.runs]
        elif self.kind == "bullets":
            out["items"] = [[r.as_dict() for r in item] for item in self.items]
        return out

    def plain(self) -> str:
        """Текстът без оформление — за заглавия и абзаци."""
        return "".join(r.text for r in self.runs)


def parse_runs(text: str) -> list[Run]:
    """Разделя реда на отрязъци по `**получер**`.

    Незатворен `**` оставя остатъка получер — нарочно, вместо да се хвърля
    грешка: офертата се пише на живо и половин знак не е причина да спре
    предварителният преглед.
    """
    runs: list[Run] = []
    buffer: list[str] = []
    bold = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\" and i + 1 < len(text) and text[i + 1] in _ESCAPABLE:
            buffer.append(text[i + 1])
            i += 2
            continue
        if text.startswith("**", i):
            if buffer:
                runs.append(Run("".join(buffer), bold))
                buffer = []
            bold = not bold
            i += 2
            continue
        buffer.append(char)
        i += 1
    if buffer:
        runs.append(Run("".join(buffer), bold))
    return [r for r in runs if r.text]


def _heading_level(line: str) -> tuple[int, str] | None:
    """`## Текст` → (2, "Текст"). Решетка без интервал след нея не е заглавие."""
    stripped = line.lstrip()
    for level in (3, 2, 1):
        prefix = "#" * level
        if stripped.startswith(prefix + " "):
            return level, stripped[level + 1 :].strip()
    return None


def _is_bullet(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("* ") or stripped == "*"


def parse(body: str) -> list[Block]:
    """Превръща текста на офертата в блокове за рисуване."""
    blocks: list[Block] = []
    paragraph: list[str] = []
    bullets: list[list[Run]] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append(Block("paragraph", runs=parse_runs(" ".join(paragraph))))
            paragraph = []

    def flush_bullets() -> None:
        nonlocal bullets
        if bullets:
            blocks.append(Block("bullets", items=bullets))
            bullets = []

    def flush_all() -> None:
        flush_paragraph()
        flush_bullets()

    for raw in (body or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_all()
            continue

        if line.strip() in (ITEMS_MARKER, ITEMS_MARKER_LATIN):
            flush_all()
            blocks.append(Block("items"))
            continue

        heading = _heading_level(line)
        if heading is not None:
            flush_all()
            level, text = heading
            blocks.append(Block(f"h{level}", runs=parse_runs(text)))  # type: ignore[arg-type]
            continue

        if _is_bullet(line):
            flush_paragraph()
            bullets.append(parse_runs(line.lstrip()[1:].strip()))
            continue

        flush_bullets()
        paragraph.append(line.strip())

    flush_all()
    return blocks


def has_items_marker(body: str) -> bool:
    """Има ли в текста място за таблицата с позициите."""
    return any(b.kind == "items" for b in parse(body))
