"""Editable post templates.

A template is Telegram HTML with two kinds of markers:

* ``{placeholder}`` — replaced with a product value. A line whose placeholders
  all come out empty is dropped, so missing RoApp fields never leave a
  dangling "Камера:" line.
* ``[Tag]`` at the very start of a line — the line is shown only when the
  product matches every tag on it (e.g. ``[Apple]`` or ``[Нова АКБ]``).

Templates are stored in the ``settings`` table and cached in memory so caption
rendering stays synchronous.
"""
from __future__ import annotations

import re

from bot import db

KIND_SMARTPHONE = "smartphone"
KIND_TABLET = "tablet"
KIND_LAPTOP = "laptop"
KIND_FOOTER = "footer"

KINDS = (KIND_SMARTPHONE, KIND_TABLET, KIND_LAPTOP, KIND_FOOTER)

KIND_LABELS = {
    KIND_SMARTPHONE: "📱 Смартфони",
    KIND_TABLET: "📟 Планшети",
    KIND_LAPTOP: "💻 Ноутбуки",
    KIND_FOOTER: "📝 Підвал (контакти)",
}

# Placeholder name -> description shown to the admin.
PLACEHOLDERS: dict[str, str] = {
    "name": "назва товару",
    "price": "ціна (якщо ціна знизилась — стара закреслена → нова)",
    "screen": "екран",
    "processor": "процесор",
    "camera": "камера",
    "battery": "АКБ",
    "complect": "комплектація",
    "screen_condition": "стан екрана",
    "body_condition": "стан корпусу",
    "os": "операційна система (Mac OS / Windows)",
}

# Canonical tag -> description. Matching is case-insensitive; see TAG_ALIASES.
TAGS: dict[str, str] = {
    "Apple": "товар Apple (iPhone, iPad, MacBook)",
    "Android": "будь-який товар НЕ Apple",
    "США": "Apple, американська версія (eSIM)",
    "Європа": "Apple, європейська версія",
    "LTE": "планшет з SIM / LTE",
    "WiFi": "планшет тільки з Wi-Fi",
    "Стан": "заповнено стан екрана або корпусу",
    "Нова АКБ": "акумулятор замінено на новий",
}

TAG_ALIASES = {
    "apple": "Apple",
    "android": "Android",
    "сша": "США",
    "usa": "США",
    "європа": "Європа",
    "европа": "Європа",
    "lte": "LTE",
    "sim": "LTE",
    "wifi": "WiFi",
    "wi-fi": "WiFi",
    "стан": "Стан",
    "нова акб": "Нова АКБ",
}

DEFAULT_TEMPLATES: dict[str, str] = {
    KIND_SMARTPHONE: (
        "✅ {name} ✅\n"
        "\n"
        "💸 Ціна: {price}\n"
        "\n"
        "[США] 🌍 Версія: США\n"
        "[США] 📶 SIM: тільки eSIM (без фізичної SIM)\n"
        "[Європа] 🌍 Версія: Європа\n"
        "[Європа] 📶 SIM: 1 фізична SIM + eSIM\n"
        "[Apple] 🔓 Neverlock (працює з будь-яким оператором)\n"
        "[Apple] 🔒 iCloud: чистий\n"
        "[Android] 🔒 Google акаунт: чистий\n"
        "\n"
        "[Стан] 💯 Стан:\n"
        " • Екран — {screen_condition}\n"
        " • Корпус — {body_condition}\n"
        "\n"
        "🖥 Екран: {screen}\n"
        "⚡ Процесор: {processor}\n"
        "📸 Камера: {camera}\n"
        "🔋 АКБ: {battery}\n"
        "\n"
        "[Apple] ✅ Перевірений: Face ID • Камери • Динаміки • NFC\n"
        "[Android] ✅ Перевірений: Камери • Динаміки • NFC\n"
        "📦 Комплектація: {complect}\n"
        "🛡 Гарантія: 1 міс.\n"
        "[Нова АКБ] 🔋 Гарантія на АКБ: 6 міс."
    ),
    KIND_TABLET: (
        "✅ {name} ✅\n"
        "\n"
        "💸 Ціна: {price}\n"
        "\n"
        "[LTE] 📶 SIM: LTE (SIM)\n"
        "[WiFi] 📶 SIM: WiFi only\n"
        "[Apple] 🔒 iCloud: чистий\n"
        "[Android] 🔒 Google акаунт: чистий\n"
        "\n"
        "[Стан] 💯 Стан:\n"
        " • Екран — {screen_condition}\n"
        " • Корпус — {body_condition}\n"
        "\n"
        "🖥 Екран: {screen}\n"
        "⚡ Процесор: {processor}\n"
        "📸 Камера: {camera}\n"
        "🔋 АКБ: {battery}\n"
        "\n"
        "✅ Перевірений: Екран • Сенсор • Камери • Wi-Fi\n"
        "📦 Комплектація: {complect}\n"
        "🛡 Гарантія: 1 міс."
    ),
    KIND_LAPTOP: (
        "✅ {name} ✅\n"
        "\n"
        "💸 Ціна: {price}\n"
        "\n"
        "[Стан] 💯 Стан:\n"
        " • Екран — {screen_condition}\n"
        " • Корпус — {body_condition}\n"
        "\n"
        "🖥 Екран: {screen}\n"
        "⚡ Процесор: {processor}\n"
        "🔋 АКБ: {battery}\n"
        "\n"
        "✅ Перевірений: Клавіатура • Тачпад • Порти • Wi-Fi\n"
        "🌐 ОС: {os}\n"
        "📦 Комплектація: {complect}\n"
        "🛡 Гарантія: 1 міс."
    ),
    KIND_FOOTER: (
        "━━━━━━━━━━━━━━━\n"
        "🔧 Ремонт • 📱 Продаж • ♻️ Обмін • Викуп\n"
        '🌐 <a href="https://sotik.in.ua">SOTIK.in.ua</a> - Ціни нижче ніж задарма!\n'
        "📍 Козятин, Героїв Майдану 20\n"
        '📞 <a href="https://t.me/sotik_ua">097 985 09 92</a>'
    ),
}

MAX_TEMPLATE_LEN = 3000
MAX_FOOTER_LEN = 500

_PLACEHOLDER_RE = re.compile(r"\{([^{}\n]*)\}")
# Leading HTML markup, then one or more [Tag] markers, then optional spaces.
_TAG_PREFIX_RE = re.compile(r"^((?:\s*<[^>]+>)*)\s*((?:\[[^\[\]\n]+\]\s*)+)")
_TAG_RE = re.compile(r"\[([^\[\]\n]+)\]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")

_cache: dict[str, str] = {}


def _setting_key(kind: str) -> str:
    return f"template_{kind}"


async def load_templates() -> None:
    """Load custom templates from the DB into the in-memory cache."""
    _cache.clear()
    for kind in KINDS:
        value = await db.get_setting(_setting_key(kind))
        if value:
            _cache[kind] = value


def get_template(kind: str) -> str:
    return _cache.get(kind) or DEFAULT_TEMPLATES[kind]


def is_custom(kind: str) -> bool:
    return kind in _cache


async def save_template(kind: str, text: str) -> None:
    await db.set_setting(_setting_key(kind), text)
    _cache[kind] = text


async def reset_template(kind: str) -> None:
    await db.delete_setting(_setting_key(kind))
    _cache.pop(kind, None)


def _canonical_tag(raw: str) -> str | None:
    return TAG_ALIASES.get(" ".join(raw.lower().split()))


def validate_template(kind: str, text: str) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for a template the admin sent."""
    errors: list[str] = []
    warnings: list[str] = []

    if not text.strip():
        return ["Шаблон порожній."], warnings

    if kind == KIND_FOOTER:
        if len(text) > MAX_FOOTER_LEN:
            errors.append(f"Підвал задовгий ({len(text)} симв.), максимум — {MAX_FOOTER_LEN}.")
        if _PLACEHOLDER_RE.search(text):
            errors.append("У підвалі не можна використовувати {поля} — тільки звичайний текст.")
        for line in text.split("\n"):
            if _TAG_PREFIX_RE.match(line):
                errors.append("У підвалі не можна використовувати [позначки].")
                break
        return errors, warnings

    if len(text) > MAX_TEMPLATE_LEN:
        errors.append(f"Шаблон задовгий ({len(text)} симв.), максимум — {MAX_TEMPLATE_LEN}.")

    unknown_ph = sorted({p for p in _PLACEHOLDER_RE.findall(text) if p not in PLACEHOLDERS})
    if unknown_ph:
        listed = ", ".join("{" + p + "}" for p in unknown_ph)
        errors.append(f"Невідомі поля: {listed}. Перевірте написання (латиницею, без пробілів).")

    unknown_tags: list[str] = []
    for line in text.split("\n"):
        m = _TAG_PREFIX_RE.match(line)
        if not m:
            continue
        for raw in _TAG_RE.findall(m.group(2)):
            if _canonical_tag(raw) is None and raw not in unknown_tags:
                unknown_tags.append(raw)
    if unknown_tags:
        listed = ", ".join(f"[{t}]" for t in unknown_tags)
        errors.append(f"Невідомі позначки на початку рядка: {listed}.")

    if "{name}" not in text:
        warnings.append("У шаблоні немає {name} — у пості не буде назви товару.")
    if "{price}" not in text:
        warnings.append("У шаблоні немає {price} — у пості не буде ціни.")

    return errors, warnings


def render(template: str, values: dict[str, str], flags: dict[str, bool]) -> str:
    """Render a template.

    ``values`` must already be HTML-escaped. ``flags`` maps canonical tag
    names to whether the product matches. Markup on dropped lines is carried
    over to the next kept line, so formatting spanning several lines never
    leaves an unclosed HTML tag behind.
    """
    out: list[str] = []
    carry = ""

    for line in template.split("\n"):
        m = _TAG_PREFIX_RE.match(line)
        if m:
            tags = [_canonical_tag(t) for t in _TAG_RE.findall(m.group(2))]
            line = m.group(1) + line[m.end():]
            if not all(t is not None and flags.get(t, False) for t in tags):
                carry += "".join(_HTML_TAG_RE.findall(line))
                continue

        names = _PLACEHOLDER_RE.findall(line)
        if names and not any(values.get(n, "").strip() for n in names):
            carry += "".join(_HTML_TAG_RE.findall(line))
            continue

        line = _PLACEHOLDER_RE.sub(lambda mm: values.get(mm.group(1), ""), line)
        out.append(carry + line)
        carry = ""

    if carry:
        if out:
            out[-1] += carry
        else:
            out.append(carry)

    return _strip_empty_pairs(_collapse_blank_lines(out))


_EMPTY_PAIR_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)[^>]*></\1>")


def _strip_empty_pairs(text: str) -> str:
    """Remove ``<b></b>``-style pairs that wrap nothing."""
    while True:
        new = _EMPTY_PAIR_RE.sub("", text)
        if new == text:
            return text
        text = new


def _is_blank(line: str) -> bool:
    return not _HTML_TAG_RE.sub("", line).strip()


def _collapse_blank_lines(lines: list[str]) -> str:
    """Drop leading/trailing blank lines and squeeze runs of blanks to one."""
    result: list[str] = []
    carry = ""
    for line in lines:
        if _is_blank(line) and (not result or _is_blank(result[-1])):
            carry += "".join(_HTML_TAG_RE.findall(line))
            continue
        result.append(carry + line)
        carry = ""
    while result and _is_blank(result[-1]):
        carry = "".join(_HTML_TAG_RE.findall(result.pop())) + carry
    if carry:
        if result:
            result[-1] += carry
        else:
            result.append(carry)
    return "\n".join(result)


_OPEN_CLOSE_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)[^>]*>")


def close_open_tags(text: str) -> str:
    """Drop a cut-off trailing tag and close any tags left open."""
    text = re.sub(r"<[^>]*$", "", text)
    stack: list[str] = []
    for closing, name in _OPEN_CLOSE_RE.findall(text):
        name = name.lower()
        if closing:
            if name in stack:
                while stack and stack.pop() != name:
                    pass
        else:
            stack.append(name)
    return text + "".join(f"</{name}>" for name in reversed(stack))
