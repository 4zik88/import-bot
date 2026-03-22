from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import InputMediaPhoto, Message

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
) -> list[Message] | None:
    try:
        messages = await bot.send_media_group(chat_id=channel_id, media=media)
        await asyncio.sleep(SEND_DELAY)
        return messages
    except TelegramRetryAfter as e:
        await _handle_retry(e)
        return await publish_media_group(bot, channel_id, media)
    except Exception as e:
        logger.error("Error publishing to channel %s: %s", channel_id, e)
        return None


async def publish_text(
    bot: Bot,
    channel_id: str,
    text: str,
) -> Message | None:
    try:
        msg = await bot.send_message(chat_id=channel_id, text=text, parse_mode="HTML")
        await asyncio.sleep(SEND_DELAY)
        return msg
    except TelegramRetryAfter as e:
        await _handle_retry(e)
        return await publish_text(bot, channel_id, text)
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
        )
        await asyncio.sleep(SEND_DELAY)
        return True
    except TelegramRetryAfter as e:
        await _handle_retry(e)
        return await edit_text(bot, channel_id, message_id, text)
    except Exception:
        return False
