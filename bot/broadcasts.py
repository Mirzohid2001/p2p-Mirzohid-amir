"""
Рассылки с возможностью удаления.

Каждая рассылка сохраняется в broadcasts.json рядом с ботом: кому и какое
сообщение ушло. /delbroadcast удаляет последнюю неудалённую рассылку у всех
получателей. Telegram даёт боту удалять свои сообщения только в течение 48 часов.
"""
import asyncio
import json
import logging
import os
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "broadcasts.json")
KEEP = 20                      # сколько последних рассылок помнить
DELETE_LIMIT = 48 * 3600       # лимит Telegram на удаление, сек
SAFETY = 10 * 60               # запас, чтобы не упереться в лимит посреди удаления
PAUSE = 0.05                   # пауза между запросами к Telegram

log = logging.getLogger(__name__)
_lock = asyncio.Lock()


def _load():
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(items):
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items[-KEEP:], f)
    os.replace(tmp, STORE)


def _fmt_age(seconds):
    h, m = int(seconds // 3600), int(seconds % 3600 // 60)
    return f"{h} ч {m} мин" if h else f"{m} мин"


def _last_active(items):
    for b in reversed(items):
        if not b.get("deleted"):
            return b
    return None


async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, user_ids):
    """Копирует сообщение админа всем пользователям и запоминает отправленные сообщения."""
    admin_id = update.effective_user.id
    src_chat_id = update.effective_chat.id
    src_message_id = update.message.message_id
    preview = (update.message.text or update.message.caption or "[фото]").strip()[:60]

    await update.message.reply_text(f"🚀 Начинаю рассылку...\nПолучателей: {len(user_ids)}")

    sent = []
    failed = 0
    for uid in user_ids:
        try:
            msg = await context.bot.copy_message(chat_id=uid, from_chat_id=src_chat_id, message_id=src_message_id)
            sent.append([uid, msg.message_id])
        except Exception:
            failed += 1
        await asyncio.sleep(PAUSE)

    async with _lock:
        items = _load()
        items.append({
            "id": int(time.time() * 1000),
            "sent_at": time.time(),
            "admin": admin_id,
            "preview": preview,
            "messages": sent,
            "deleted": False,
        })
        _save(items)

    await update.message.reply_text(
        "✅ Рассылка завершена!\n\n"
        f"📤 Отправлено: {len(sent)}\n"
        f"❌ Ошибок: {failed}\n\n"
        "Удалить её у всех можно командой /delbroadcast в течение 48 часов."
    )


async def delbroadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE, is_admin):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Нет доступа.")
        return

    b = _last_active(_load())
    if not b:
        await update.message.reply_text("Нет рассылок, которые можно удалить.")
        return

    age = time.time() - b["sent_at"]
    if age > DELETE_LIMIT - SAFETY:
        await update.message.reply_text(
            f"Последней рассылке уже {_fmt_age(age)}. Telegram даёт удалять сообщения "
            "только в течение 48 часов, поэтому удалить её уже нельзя."
        )
        return

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🗑 Да, удалить у всех", callback_data=f"delbc_yes_{b['id']}"),
        InlineKeyboardButton("Отмена", callback_data=f"delbc_no_{b['id']}"),
    ]])
    await update.message.reply_text(
        "Удалить последнюю рассылку?\n\n"
        f"«{b['preview']}»\n"
        f"Отправлена {_fmt_age(age)} назад, получателей: {len(b['messages'])}.\n\n"
        "Сообщение исчезнет у всех пользователей. Отменить это нельзя.",
        reply_markup=kb,
    )


async def delbroadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, is_admin):
    query = update.callback_query
    await query.answer()
    if not await is_admin(query.from_user.id):
        await query.message.reply_text("⛔️ Нет доступа.")
        return

    _, action, bc_id = query.data.split("_", 2)
    if action == "no":
        await query.message.edit_text("Удаление отменено.")
        return

    async with _lock:
        items = _load()
        b = next((x for x in items if str(x["id"]) == bc_id), None)
        if not b or b.get("deleted"):
            await query.message.edit_text("Эта рассылка уже удалена.")
            return
        if time.time() - b["sent_at"] > DELETE_LIMIT:
            await query.message.edit_text("Прошло больше 48 часов, Telegram уже не даёт удалить эту рассылку.")
            return
        b["deleted"] = True  # помечаем сразу, чтобы второе нажатие не запустило удаление повторно
        _save(items)

    await query.message.edit_text(f"🗑 Удаляю рассылку у {len(b['messages'])} пользователей...")

    ok = failed = 0
    for chat_id, message_id in b["messages"]:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            ok += 1
        except Exception:
            failed += 1
        await asyncio.sleep(PAUSE)

    log.info("Broadcast %s deleted by %s: ok=%s failed=%s", bc_id, query.from_user.id, ok, failed)
    await query.message.reply_text(
        "✅ Рассылка удалена.\n\n"
        f"🗑 Удалено: {ok}\n"
        f"❌ Не удалось: {failed}"
        + ("\n\nНе удалось — обычно у тех, кто сам удалил сообщение или чат с ботом." if failed else "")
    )
