from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InputMediaPhoto, LinkPreviewOptions, Message

logger = logging.getLogger(__name__)

SEND_DELAY = 5.0  # seconds between sends


async def _handle_retry(e: TelegramRetryAfter) -> None:
    wait = e.retry_after + 2
    logger.warning("Rate limited, sleeping %s seconds", wait)
    await asyncio.sleep(wait)


async def publish_media_group(
    bot: Bot,
    channel_id: str,
    media: list[InputMediaPhoto],
    silent: bool = False,
) -> list[Message] | None:
    try:
        messages = await bot.send_media_group(chat_id=channel_id, media=media, disable_notification=silent)
        await asyncio.sleep(SEND_DELAY)
        return messages
    except TelegramRetryAfter as e:
        await _handle_retry(e)
        return await publish_media_group(bot, channel_id, media, silent=silent)
    except Exception as e:
        logger.error("Error publishing to channel %s: %s", channel_id, e)
        return None


async def publish_text(
    bot: Bot,
    channel_id: str,
    text: str,
    silent: bool = False,
) -> Message | None:
    try:
        msg = await bot.send_message(
            chat_id=channel_id, text=text, parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            disable_notification=silent,
        )
        await asyncio.sleep(SEND_DELAY)
        return msg
    except TelegramRetryAfter as e:
        await _handle_retry(e)
        return await publish_text(bot, channel_id, text, silent=silent)
    except Exception as e:
        logger.error("Error publishing text to channel %s: %s", channel_id, e)
        return None


async def delete_message(bot: Bot, channel_id: str, message_id: str) -> bool:
    try:
        await bot.delete_message(chat_id=channel_id, message_id=int(message_id))
        await asyncio.sleep(SEND_DELAY)
        return True
    except TelegramRetryAfter as e:
        await _handle_retry(e)
        return await delete_message(bot, channel_id, message_id)
    except Exception as e:
        logger.warning("Could not delete message %s: %s", message_id, e)
        return False


async def message_exists(bot: Bot, channel_id: str, message_id: str) -> bool | None:
    """Best-effort check whether a channel message still exists.

    Returns True (exists), False (confirmed deleted), or None (unknown — caller
    must treat as "exists" to stay safe). Probes with a no-op reply-markup edit:
    the bot's channel posts never carry an inline keyboard, so this makes no
    visible change and sends no notification — it just asks Telegram whether the
    message is there. We only return False on an explicit "message not found",
    never on generic errors, so auto-heal can never re-post over a live message.
    """
    try:
        await bot.edit_message_reply_markup(chat_id=channel_id, message_id=int(message_id))
        return True
    except TelegramRetryAfter as e:
        await _handle_retry(e)
        return await message_exists(bot, channel_id, message_id)
    except TelegramBadRequest as e:
        text = str(e).lower()
        # Chat-level problems say nothing about this specific message — stay safe.
        if "chat not found" in text or "blocked" in text or "not enough rights" in text:
            return None
        if "message to edit not found" in text or "message_id_invalid" in text \
           or "message identifier is not specified" in text:
            return False
        # "message is not modified", "message can't be edited", etc. -> it exists.
        return True
    except Exception as e:
        logger.warning("Existence probe failed for message %s: %s", message_id, e)
        return None


async def edit_caption(bot: Bot, channel_id: str, message_id: str, caption: str) -> bool:
    try:
        await bot.edit_message_caption(
            chat_id=channel_id, message_id=int(message_id),
            caption=caption, parse_mode="HTML",
        )
        await asyncio.sleep(SEND_DELAY)
        return True
    except TelegramRetryAfter as e:
        await _handle_retry(e)
        return await edit_caption(bot, channel_id, message_id, caption)
    except Exception:
        return False


async def edit_text(bot: Bot, channel_id: str, message_id: str, text: str) -> bool:
    try:
        await bot.edit_message_text(
            chat_id=channel_id, message_id=int(message_id),
            text=text, parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        await asyncio.sleep(SEND_DELAY)
        return True
    except TelegramRetryAfter as e:
        await _handle_retry(e)
        return await edit_text(bot, channel_id, message_id, text)
    except Exception:
        return False
