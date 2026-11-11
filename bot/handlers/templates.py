"""/template — edit post templates from Telegram: view, edit, preview, reset."""
from __future__ import annotations

import html
import logging

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import LinkPreviewOptions, Message

from bot.config import settings
from bot.roapp.models import RoAppProduct
from bot.telegram.formatter import MAX_CAPTION, render_caption
from bot.telegram.templates import (
    DEFAULT_TEMPLATES, KIND_FOOTER, KIND_LABELS, KIND_LAPTOP, KIND_SMARTPHONE,
    KIND_TABLET, KINDS, PLACEHOLDERS, TAGS, get_template, is_custom,
    reset_template, save_template, validate_template,
)

router = Router()
router.message.filter(F.from_user.id.in_(settings.all_admin_ids))
router.callback_query.filter(F.from_user.id.in_(settings.all_admin_ids))

logger = logging.getLogger(__name__)

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


class TemplateStates(StatesGroup):
    waiting_text = State()


# --- Sample products used for previews -------------------------------------

def _sample(name: str, price: float, **fields: str) -> RoAppProduct:
    ids = {
        "processor": "f6601600", "camera": "f6601601", "screen": "f6601602",
        "battery": "f6601603", "complect": "f6617798",
        "screen_condition": "f10328326", "body_condition": "f10328327",
    }
    return RoAppProduct(
        name=name, price=price,
        custom_attributes={ids[k]: v for k, v in fields.items()},
    )


# (description, product, old price) per kind; the footer previews on a smartphone.
SAMPLES: dict[str, list[tuple[str, RoAppProduct, float | None]]] = {
    KIND_SMARTPHONE: [
        ("iPhone, Європа", _sample(
            "Apple iPhone 14 Pro Max 256 Deep Purple", 28000,
            screen='6.7" LTPO Super Retina XDR OLED 120Hz',
            processor="Apple A16 Bionic", camera="48 MP + 12 MP + 12 MP",
            battery="4323 мАч (84%)", complect="Коробка",
            screen_condition="A+ (Ідеал або майже)", body_condition="A (Легкі потертості)",
        ), None),
        ("Android, знижка ціни, нова АКБ, без стану", _sample(
            "Samsung Galaxy S23 8/128GB Black", 15500,
            screen='6.1" Dynamic AMOLED 2X 120Hz', processor="Snapdragon 8 Gen 2",
            battery="3900 мАч (заміна, нова)",
        ), 17000),
    ],
    KIND_TABLET: [
        ("iPad, Wi-Fi", _sample(
            "Apple iPad Air 5 64GB Wi-Fi Blue", 16000,
            screen='10.9" Liquid Retina', processor="Apple M1", camera="12 MP",
            battery="7606 мАч (91%)", complect="Без коробки",
            screen_condition="A", body_condition="A",
        ), None),
    ],
    KIND_LAPTOP: [
        ("MacBook", _sample(
            "Apple MacBook Air 13 M1 8/256GB Space Gray", 21000,
            screen='13.3" Retina IPS', processor="Apple M1", battery="88%, 312 циклів",
            complect="Зарядний пристрій", screen_condition="A+", body_condition="A",
        ), None),
    ],
}
SAMPLES[KIND_FOOTER] = SAMPLES[KIND_SMARTPHONE][:1]


def _render_samples(kind: str, draft: str) -> list[tuple[str, str]]:
    """Render ``draft`` on the sample products for ``kind``."""
    out = []
    for label, product, old_price in SAMPLES[kind]:
        if kind == KIND_FOOTER:
            caption = render_caption(KIND_SMARTPHONE, product, old_price, footer=draft)
        else:
            caption = render_caption(kind, product, old_price, template=draft)
        out.append((label, caption))
    return out


# --- Texts -----------------------------------------------------------------

def _menu_kb() -> types.InlineKeyboardMarkup:
    rows = []
    for kind in KINDS:
        mark = " ✏️" if is_custom(kind) else ""
        rows.append([types.InlineKeyboardButton(
            text=KIND_LABELS[kind] + mark, callback_data=f"tpl:open:{kind}")])
    rows.append([types.InlineKeyboardButton(text="❓ Як це працює", callback_data="tpl:help")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


MENU_TEXT = (
    "<b>Шаблони постів</b>\n\n"
    "Оберіть, який шаблон змінити. ✏️ — шаблон уже змінено (не стандартний).\n\n"
    "Підвал (контакти, сайт, адреса) додається в кінець кожного поста автоматично."
)


def _reference_text(kind: str) -> str:
    if kind == KIND_FOOTER:
        return (
            "<b>Підвал</b> — це блок у кінці кожного поста (контакти, сайт, адреса).\n"
            "Він однаковий для всіх категорій і для постів «ПРОДАНО».\n\n"
            "Тут не можна використовувати {поля} і [позначки] — тільки звичайний текст. "
            "Посилання та жирний шрифт — через меню форматування Telegram."
        )
    ph = "\n".join(f"<code>{{{n}}}</code> — {d}" for n, d in PLACEHOLDERS.items())
    tags = "\n".join(f"<code>[{n}]</code> — {d}" for n, d in TAGS.items())
    return (
        f"<b>Шаблон: {KIND_LABELS[kind]}</b>\n\n"
        "<b>Поля</b> — замість них бот підставить дані з RoApp:\n"
        f"{ph}\n\n"
        "Якщо поле в товарі не заповнене — <b>увесь рядок</b> з цим полем не виводиться.\n\n"
        "<b>Позначки</b> на початку рядка — рядок показується тільки якщо умова виконується:\n"
        f"{tags}\n\n"
        "Приклад: <code>[Apple] 🔒 iCloud: чистий</code> — цей рядок буде тільки в постах Apple."
    )


HELP_TEXT = (
    "<b>Як змінити шаблон поста</b>\n\n"
    "1. /template → оберіть категорію (Смартфони, Планшети, Ноутбуки або Підвал).\n"
    "2. Бот надішле поточний шаблон окремим повідомленням. "
    "Скопіюйте його (утримуйте повідомлення → «Копіювати»).\n"
    "3. Натисніть «✏️ Змінити», вставте текст у поле вводу, відредагуйте й надішліть.\n"
    "4. Бот перевірить шаблон і покаже, як виглядатимуть пости на прикладах товарів.\n"
    "5. Якщо все добре — «✅ Зберегти». Якщо ні — просто надішліть виправлений текст ще раз.\n\n"
    "<b>Правила</b>\n"
    "• <code>{name}</code>, <code>{price}</code> та інші <b>поля</b> пишуться латиницею у фігурних дужках, "
    "точно як у списку. Бот підставить дані товару.\n"
    "• Якщо поле в товарі порожнє — рядок з ним зникає з поста.\n"
    "• <code>[Apple]</code>, <code>[Android]</code> та інші <b>позначки</b> ставляться на самому початку рядка. "
    "Рядок буде видно тільки для товарів, що підходять.\n"
    "• Порожні рядки між блоками зберігаються; два порожні рядки підряд стають одним.\n"
    "• Жирний, курсив, закреслений, посилання — через стандартне меню форматування Telegram "
    "(виділіть текст → «Форматування»).\n"
    "• Підвал з контактами додається до кожного поста автоматично — його не треба вставляти в шаблон.\n"
    "• Максимальна довжина поста в Telegram — 1024 символи. Якщо пост довший, "
    "бот обріже середину, а підвал залишить.\n\n"
    "<b>Коли застосовуються зміни</b>\n"
    "• Нові пости одразу публікуються з новим шаблоном.\n"
    "• Щоб оновити <b>вже опубліковані</b> пости, запустіть /import — бот перепише підписи "
    "всіх постів у каналі. Це може зайняти кілька хвилин (Telegram обмежує швидкість).\n\n"
    "<b>Якщо щось пішло не так</b>\n"
    "/template → категорія → «↩️ Стандартний шаблон» поверне шаблон до початкового вигляду.\n"
    "/cancel — вийти з редагування без змін."
)


def _kind_kb(kind: str) -> types.InlineKeyboardMarkup:
    rows = [
        [types.InlineKeyboardButton(text="✏️ Змінити", callback_data=f"tpl:edit:{kind}")],
        [types.InlineKeyboardButton(text="👁 Попередній перегляд", callback_data=f"tpl:prev:{kind}")],
    ]
    if is_custom(kind):
        rows.append([types.InlineKeyboardButton(
            text="↩️ Стандартний шаблон", callback_data=f"tpl:reset:{kind}")])
    rows.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="tpl:menu")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_template(message: Message, text: str) -> None:
    """Send a template as its own message so it can be copied as-is."""
    try:
        await message.answer(text, parse_mode="HTML", link_preview_options=NO_PREVIEW)
    except Exception:
        await message.answer(text, parse_mode=None, link_preview_options=NO_PREVIEW)


async def _send_previews(message: Message, kind: str, draft: str) -> list[str]:
    """Send preview posts; return problems that must block saving."""
    problems: list[str] = []
    for label, caption in _render_samples(kind, draft):
        await message.answer(f"👁 <b>Приклад: {label}</b>", parse_mode="HTML")
        try:
            await message.answer(caption, parse_mode="HTML", link_preview_options=NO_PREVIEW)
        except Exception as e:
            logger.warning("Template preview rejected by Telegram: %s", e)
            problems.append(f"Telegram не прийняв пост «{label}»: {html.escape(str(e))}")
    return problems


# --- Handlers --------------------------------------------------------------

@router.message(Command("template"))
async def cmd_template(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(MENU_TEXT, parse_mode="HTML", reply_markup=_menu_kb())


@router.callback_query(F.data == "tpl:menu")
async def cb_menu(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(MENU_TEXT, parse_mode="HTML", reply_markup=_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "tpl:help")
async def cb_help(callback: types.CallbackQuery) -> None:
    await callback.message.answer(HELP_TEXT, parse_mode="HTML")
    await callback.answer()


def _kind_from(data: str) -> str | None:
    kind = data.rsplit(":", 1)[-1]
    return kind if kind in KINDS else None


@router.callback_query(F.data.startswith("tpl:open:"))
async def cb_open(callback: types.CallbackQuery, state: FSMContext) -> None:
    kind = _kind_from(callback.data)
    if not kind:
        await callback.answer()
        return
    await state.clear()
    status = "✏️ змінений" if is_custom(kind) else "стандартний"
    await callback.message.answer(_reference_text(kind), parse_mode="HTML")
    await callback.message.answer(f"Поточний шаблон ({status}) — наступним повідомленням 👇")
    await _send_template(callback.message, get_template(kind))
    await callback.message.answer("Що зробити?", reply_markup=_kind_kb(kind))
    await callback.answer()


@router.callback_query(F.data.startswith("tpl:prev:"))
async def cb_preview(callback: types.CallbackQuery) -> None:
    kind = _kind_from(callback.data)
    if not kind:
        await callback.answer()
        return
    await callback.answer()
    await _send_previews(callback.message, kind, get_template(kind))
    await callback.message.answer("Що зробити?", reply_markup=_kind_kb(kind))


@router.callback_query(F.data.startswith("tpl:edit:"))
async def cb_edit(callback: types.CallbackQuery, state: FSMContext) -> None:
    kind = _kind_from(callback.data)
    if not kind:
        await callback.answer()
        return
    await state.set_state(TemplateStates.waiting_text)
    await state.update_data(kind=kind, draft=None)
    await callback.message.answer(
        f"✏️ <b>{KIND_LABELS[kind]}</b>\n\n"
        "Скопіюйте поточний шаблон (повідомлення вище), відредагуйте й надішліть "
        "новий текст <b>одним повідомленням</b>.\n\n"
        "/cancel — скасувати.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(TemplateStates.waiting_text)
async def on_template_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    kind = data.get("kind")
    if kind not in KINDS:
        await state.clear()
        return

    if not message.text:
        await message.answer("Надішліть шаблон текстом (без фото). /cancel — скасувати.")
        return
    if message.text.startswith("/"):
        await message.answer(
            "Схоже на команду, а не шаблон. Надішліть текст шаблону або /cancel, щоб вийти."
        )
        return

    draft = message.html_text
    errors, warnings = validate_template(kind, draft)
    if errors:
        await message.answer(
            "❌ <b>Шаблон не збережено:</b>\n\n"
            + "\n".join(f"• {html.escape(e)}" for e in errors)
            + "\n\nВиправте й надішліть ще раз, або /cancel.\n"
            "Список полів і позначок: /template → категорія.",
            parse_mode="HTML",
        )
        return

    problems = await _send_previews(message, kind, draft)
    longest = max((len(c) for _, c in _render_samples(kind, draft)), default=0)
    if longest >= MAX_CAPTION:
        warnings.append(
            f"Пост виходить задовгим (ліміт Telegram — {MAX_CAPTION} символів). "
            "Частина тексту буде обрізана — скоротіть шаблон."
        )

    if problems:
        await message.answer(
            "❌ <b>Шаблон не можна зберегти:</b>\n\n"
            + "\n".join(f"• {p}" for p in problems)
            + "\n\nВиправте й надішліть ще раз, або /cancel.",
            parse_mode="HTML",
        )
        return

    await state.update_data(draft=draft)
    note = ""
    if warnings:
        note = "⚠️ <b>Зверніть увагу:</b>\n" + "\n".join(
            f"• {html.escape(w)}" for w in warnings) + "\n\n"
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ Зберегти", callback_data="tpl:save")],
        [types.InlineKeyboardButton(text="❌ Скасувати", callback_data="tpl:cancel")],
    ])
    await message.answer(
        f"{note}Так виглядатимуть пости з новим шаблоном (вище).\n\n"
        "Зберегти? Або надішліть виправлений текст ще раз.",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.callback_query(F.data == "tpl:save")
async def cb_save(callback: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    kind, draft = data.get("kind"), data.get("draft")
    if kind not in KINDS or not draft:
        await callback.answer("Немає шаблону для збереження. Почніть знову: /template", show_alert=True)
        return
    await save_template(kind, draft)
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Шаблон «{KIND_LABELS[kind]}» збережено.\n\n"
        "Нові пости вже публікуватимуться з ним.\n"
        "Щоб оновити вже опубліковані пости — запустіть /import "
        "(може зайняти кілька хвилин).",
    )
    await callback.answer("Збережено")


@router.callback_query(F.data == "tpl:cancel")
async def cb_cancel(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Скасовано, шаблон не змінено.")
    await callback.answer()


@router.callback_query(F.data.startswith("tpl:reset:"))
async def cb_reset(callback: types.CallbackQuery) -> None:
    kind = _kind_from(callback.data)
    if not kind:
        await callback.answer()
        return
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Так, повернути стандартний", callback_data=f"tpl:reset_ok:{kind}")],
        [types.InlineKeyboardButton(text="Ні", callback_data=f"tpl:open:{kind}")],
    ])
    await callback.message.answer(
        f"Повернути стандартний шаблон «{KIND_LABELS[kind]}»?\n"
        "Ваш змінений шаблон буде видалено. Стандартний — наступним повідомленням 👇",
        reply_markup=None,
    )
    await _send_template(callback.message, DEFAULT_TEMPLATES[kind])
    await callback.message.answer("Підтвердіть:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("tpl:reset_ok:"))
async def cb_reset_ok(callback: types.CallbackQuery, state: FSMContext) -> None:
    kind = _kind_from(callback.data)
    if not kind:
        await callback.answer()
        return
    await reset_template(kind)
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"↩️ Шаблон «{KIND_LABELS[kind]}» повернуто до стандартного.\n"
        "Щоб оновити вже опубліковані пости — запустіть /import.",
    )
    await callback.answer()
