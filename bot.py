# bot.py - Yamato 💜 - Versión corregida
# Compatible con python-telegram-bot v20.6
# RECUERDA: reemplaza TOKEN por tu token real antes de ejecutar.

import logging
import html
import asyncio
import copy
from datetime import datetime
from typing import Dict, Any, List, Optional
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------
TOKEN = "8284507264:AAGnJ3Pz_EVDMkGKxmiaakLjfKfEJIqhSwQ"  # <- reemplaza aquí con tu token real
STORAGE_CHAT_ID = -1003414541916
MUSICAS_TOPIC_ID = 2  # solo para música (guardar)
POST_TOPICS = {
    5: "APKS",
    6: "Hollow knight",
    7: "Silksong",
    8: "GTA+AML",
}

# Autoclean (autolimpieza inteligente)
AUTOCLEAN_TTL_MINUTES = 60    # no se usa para la limpieza instantánea, sigue disponible
AUTOCLEAN_INTERVAL_SECONDS = 300
# ----------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)

# in-memory storage (no persistence)
POST_DRAFTS: Dict[int, Dict[str, Any]] = {}
TRACKED_MEDIA: Dict[int, Optional[str]] = {}  # original_message_id -> file_id

# NEW: global per-user media queue and timer/tasks
USER_MEDIA_QUEUE: Dict[int, List[Message]] = {}           # user_id -> list of Message objects
USER_QUEUE_TIMER: Dict[int, asyncio.Task] = {}            # user_id -> asyncio.Task (delay before processing)
USER_PROCESSING: Dict[int, bool] = {}                     # user_id -> bool (is processing right now)

# Message tracking to support deletion/cleanup
# Each entry: {"chat_id": int, "message_id": int, "time": timestamp_float}
USER_LAST_MESSAGES: Dict[int, List[Dict[str, Any]]] = {}  # per user, list of bot messages to delete

# ---------------- helpers ----------------

def make_default_post() -> Dict[str, Any]:
    return {
        "name": "<<< NOMBRE DEL POST AQUÍ >>>",
        "description": "<<< DESCRIPCIÓN DEL POST AQUÍ >>>",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "url": "",
        "photo_id": None,
        "gif_id": None,
        "modifications": "• No hay modificaciones aún.",
        "thread_id": None,
        "topic_id": None,
    }

def escape_html(t) -> str:
    return html.escape(str(t))

def make_progress_bar(pct: int) -> str:
    total = 10
    filled = max(0, min(total, int((pct / 100) * total)))
    bar = "■" * filled + "□" * (total - filled)
    return f"⏳ [{bar}] {pct}%"

def greeting_text(name: str) -> str:
    return f"🌸 Hola {escape_html(name)} 💜\nSoy <b>Yamato</b> — tu asistente de almacenamiento ☁️\n\n¿Qué quieres hacer?"

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 Nuevo Post ✨", callback_data="menu_newpost"),
             InlineKeyboardButton("✏️ Editar Post 💜", callback_data="menu_editpost")],
            [
             InlineKeyboardButton("🚀 Enviar Post ⚡", callback_data="menu_sendpost")],
            [InlineKeyboardButton("🎵 Guardar Música 🎧", callback_data="menu_media"),
             InlineKeyboardButton("📚 Temas 🗂️", callback_data="menu_temas")],
            [InlineKeyboardButton("🔎 ID 🔍", callback_data="menu_id")]
        ]
    )

def edit_menu(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔤 Nombre", callback_data=f"edit_field:name:{uid}"),
         InlineKeyboardButton("📝 Descripción", callback_data=f"edit_field:description:{uid}")],
        [InlineKeyboardButton("📅 Fecha", callback_data=f"edit_field:date:{uid}"),
         InlineKeyboardButton("🔗 URL", callback_data=f"edit_field:url:{uid}")],
        [InlineKeyboardButton("🖼 Foto", callback_data=f"edit_field:photo:{uid}"),
         InlineKeyboardButton("🎞 GIF", callback_data=f"edit_field:gif:{uid}")],
        [InlineKeyboardButton("🧵 Tema", callback_data=f"edit_field:topic:{uid}")],
        [InlineKeyboardButton("🛠 Modificaciones", callback_data=f"edit_field:modifications:{uid}")],
        [InlineKeyboardButton("↩️ Restaurar versión anterior", callback_data=f"restore_backup:{uid}")],
        [InlineKeyboardButton("🚀 Enviar Post", callback_data=f"prepare_publish:{uid}")],
        [InlineKeyboardButton("🔙 Volver al menú", callback_data=f"menu_back:{uid}")]
    ])

def topics_keyboard_for_editing(uid: int) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(name, callback_data=f"settopic:{tid}:{uid}")] for tid, name in POST_TOPICS.items()]
    buttons.append([InlineKeyboardButton("Cancelar", callback_data=f"menu_back:{uid}")])
    return InlineKeyboardMarkup(buttons)

def confirm_replace_photo_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Reemplazar", callback_data=f"replace_photo:yes:{uid}"),
         InlineKeyboardButton("❌ Cancelar", callback_data=f"replace_photo:no:{uid}")]
    ])

def publish_confirm_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Sí, publicar", callback_data=f"publish_yes:{uid}"),
         InlineKeyboardButton("❌ No, volver", callback_data=f"publish_no:{uid}")]
    ])

def download_button_for_post(draft: Dict[str, Any]) -> Optional[InlineKeyboardMarkup]:
    url = draft.get("url", "") if draft else ""
    if url:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⬇️ Descargar", url=url)]])
    return None

# ---------------- Message tracking helpers ----------------

async def track_and_replace(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, message_id: int):
    """
    Opción 2: antes de registrar este nuevo mensaje del bot, intentamos eliminar
    cualquier mensaje anterior del bot para ese usuario, dejando solo el último.
    """
    entries = USER_LAST_MESSAGES.get(user_id, [])[:]
    for e in entries:
        try:
            await context.bot.delete_message(chat_id=e["chat_id"], message_id=e["message_id"])
        except Exception:
            pass
    # reset list and add current
    USER_LAST_MESSAGES[user_id] = [{
        "chat_id": chat_id,
        "message_id": message_id,
        "time": datetime.now().timestamp()
    }]

async def cleanup_user_messages(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Elimina todos los mensajes rastreados para un usuario (usado por flujos que limpian)."""
    entries = USER_LAST_MESSAGES.get(user_id, [])[:]
    for e in entries:
        try:
            await context.bot.delete_message(chat_id=e["chat_id"], message_id=e["message_id"])
        except Exception:
            pass
    USER_LAST_MESSAGES[user_id] = []

async def auto_cleanup_job(context: ContextTypes.DEFAULT_TYPE):
    """Job periódico que elimina mensajes del bot más viejos que AUTOCLEAN_TTL_MINUTES."""
    now = datetime.now().timestamp()
    ttl_seconds = AUTOCLEAN_TTL_MINUTES * 60
    removed_total = 0
    for user_id, lst in list(USER_LAST_MESSAGES.items()):
        new_list = []
        for entry in lst:
            entry_time = entry.get("time", 0)
            if now - entry_time > ttl_seconds:
                try:
                    await context.bot.delete_message(chat_id=entry["chat_id"], message_id=entry["message_id"])
                    removed_total += 1
                except Exception:
                    pass
            else:
                new_list.append(entry)
        if new_list:
            USER_LAST_MESSAGES[user_id] = new_list
        else:
            USER_LAST_MESSAGES.pop(user_id, None)
    if removed_total:
        logger.info("Auto-clean removed %d bot messages.", removed_total)

# ---------------- Start & basic handlers ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name if user and user.first_name else "amigo"

    if update.message:
        # send GIF (best-effort)
        try:
            await update.message.reply_animation(
                animation="BQACAgEAAxkBAAIPumkg-circXsp3z_N-Dx0vwZ-kfSgAAIpBwACWwkJRekd6Iv-GIcmNgQ"
            )
        except Exception:
            pass

        sent = await update.message.reply_text(
            greeting_text(name),
            reply_markup=main_menu(),
            parse_mode="HTML"
        )
        await track_and_replace(context, user.id, sent.chat.id, sent.message_id)

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    tid = getattr(update.message, "message_thread_id", None) if update.message else None
    sent = await update.message.reply_text(
        f"<b>Chat ID:</b> {chat.id}\n<b>Topic ID:</b> {tid}\n<b>Your ID:</b> {update.effective_user.id}",
        parse_mode="HTML"
    )
    await track_and_replace(context, update.effective_user.id, sent.chat.id, sent.message_id)


# ---------------- Menu callback handler ----------------

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    # cleanup previous bot messages for this user (keep behavior)
    await cleanup_user_messages(context, uid)

    # try delete the message where buttons were
    try:
        await context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
    except Exception:
        pass

    if data == "menu_newpost":
        if uid in POST_DRAFTS:
            sent = await query.message.reply_text("❗ Ya tienes un borrador activo. Usa ✏️ Editar Post para modificarlo o usa 'menu_newpost_confirm' para reemplazar.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🆕 Crear nuevo (reemplazar)", callback_data=f"menu_newpost_confirm:{uid}") , InlineKeyboardButton("🔙 Volver", callback_data="menu_back")]]))
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        POST_DRAFTS[uid] = make_default_post()
        context.user_data["backup"] = copy.deepcopy(POST_DRAFTS[uid])
        sent = await query.message.reply_text("📝 Borrador creado. ¿Para qué tema será este post?", reply_markup=topics_keyboard_for_editing(uid))
        await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    if data.startswith("menu_newpost_confirm"):
        # create/replace draft
        POST_DRAFTS[uid] = make_default_post()
        context.user_data["backup"] = copy.deepcopy(POST_DRAFTS[uid])
        sent = await query.message.reply_text("📝 Nuevo borrador creado (reemplazado). ¿Para qué tema será?", reply_markup=topics_keyboard_for_editing(uid))
        await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    if data == "menu_editpost":
        if uid not in POST_DRAFTS:
            sent = await query.message.reply_text("❌ Aún no tienes ningún borrador creado 💜\nUsa el botón 📝 Nuevo Post para comenzar.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        context.user_data["backup"] = copy.deepcopy(POST_DRAFTS[uid])
        d = POST_DRAFTS[uid]
        text = (
            "<b>✏️ Editar borrador actual</b>\n\n"
            f"<b>• Nombre:</b> {escape_html(d['name'])}\n"
            f"<b>• Descripción:</b> {escape_html(d['description'])}\n"
            f"<b>• Fecha:</b> {escape_html(d['date'])}\n"
            f"<b>• URL:</b> {escape_html(d.get('url',''))}\n"
            f"<b>• Foto:</b> {'Sí' if d.get('photo_id') else '—'}\n"
            f"<b>• GIF:</b> {'Sí' if d.get('gif_id') else '—'}\n"
            f"<b>• Tema actual:</b> {POST_TOPICS.get(d.get('topic_id')) if d.get('topic_id') else '—'}\n\n"
            "Selecciona el campo a editar:"
        )
        sent = await query.message.reply_text(text, parse_mode="HTML", reply_markup=edit_menu(uid))
        await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    
        d = POST_DRAFTS[uid]
        caption = (
            "<b>📌 Vista previa del post</b>\n\n"
            f"<b>🌸 Título:</b> {escape_html(d['name'])}\n\n"
            f"💜 {escape_html(d['description'])}\n\n"
            f"👤 <b>Autor:</b> Yamato\n"
            f"📚 <b>Tema:</b> {POST_TOPICS.get(d.get('topic_id')) if d.get('topic_id') else '—'}\n"
            f"📅 <b>Fecha:</b> {escape_html(d['date'])}\n\n"
            f"🛠 <b>Modificaciones:</b>\n{escape_html(d.get('modifications','—'))}"
        )
        kb = download_button_for_post(d)
        try:
            if d.get("gif_id"):
                sent = await context.bot.send_animation(chat_id=query.message.chat_id, animation=d["gif_id"], caption=caption, parse_mode="HTML", reply_markup=kb)
            elif d.get("photo_id"):
                sent = await context.bot.send_photo(chat_id=query.message.chat_id, photo=d["photo_id"], caption=caption, parse_mode="HTML", reply_markup=kb)
            else:
                sent = await context.bot.send_message(chat_id=query.message.chat_id, text=caption, parse_mode="HTML", reply_markup=kb)
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            sent2 = await context.bot.send_message(chat_id=query.message.chat_id, text="✔️ Previsualización enviada arriba.", reply_markup=main_menu(), parse_mode="HTML")
            await track_and_replace(context, uid, sent2.chat.id, sent2.message_id)
        except Exception as e:
            logger.exception("Error mostrando previsualización: %s", e)
            sent = await query.message.reply_text("❌ Error mostrando la previsualización.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    if data == "menu_sendpost":
        if uid not in POST_DRAFTS:
            sent = await query.message.reply_text("❌ Aún no tienes ningún borrador creado 💜", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        d = POST_DRAFTS[uid]
        caption = (
            "<b>📌 Vista previa para publicar</b>\n\n"
            f"<b>🌸 Título:</b> {escape_html(d['name'])}\n\n"
            f"💜 {escape_html(d['description'])}\n\n"
            f"👤 <b>Autor:</b> Yamato\n"
            f"📚 <b>Tema:</b> {POST_TOPICS.get(d.get('topic_id')) if d.get('topic_id') else '—'}\n"
            f"📅 <b>Fecha:</b> {escape_html(d['date'])}\n\n"
            f"🛠 <b>Modificaciones:</b>\n{escape_html(d.get('modifications','—'))}"
        )
        kb = publish_confirm_keyboard(uid)
        try:
            if d.get("gif_id"):
                sent_preview = await context.bot.send_animation(chat_id=query.message.chat_id, animation=d["gif_id"], caption=caption, parse_mode="HTML", reply_markup=kb)
            elif d.get("photo_id"):
                sent_preview = await context.bot.send_photo(chat_id=query.message.chat_id, photo=d["photo_id"], caption=caption, parse_mode="HTML", reply_markup=kb)
            else:
                sent_preview = await context.bot.send_message(chat_id=query.message.chat_id, text=caption, parse_mode="HTML", reply_markup=kb)
            await track_and_replace(context, uid, sent_preview.chat.id, sent_preview.message_id)
        except Exception as e:
            logger.exception("Error preparing publish preview: %s", e)
            sent = await query.message.reply_text("❌ Error preparando la publicación.", reply_markup=edit_menu(uid))
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    if data == "menu_media":
        sent = await query.message.reply_text("🎵 Envíame un audio (solo archivos de audio) en privado y lo guardaré en el tema <b>Músicas</b> (ID 2).", parse_mode="HTML", reply_markup=main_menu())
        await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    if data == "menu_temas":
        lines = "<b>📚 Temas disponibles:</b>\n\n"
        for name in POST_TOPICS.values():
            lines += f"• <b>{escape_html(name)}</b>\n"
        sent = await query.message.reply_text(lines, parse_mode="HTML", reply_markup=main_menu())
        await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    if data == "menu_id":
        sent = await query.message.reply_text("🔎 Envíame aquí la foto o el GIF y te devolveré su file_id (no lo guardará en tu post).", parse_mode="HTML")
        await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        context.user_data["expect_id"] = True
        return

    # callbacks for edit fields and others
    if data.startswith("edit_field:"):
        try:
            _, field, raw_uid = data.split(":", 2)
            raw_uid = int(raw_uid)
        except Exception:
            sent = await query.message.reply_text("❌ Datos de callback inválidos.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        if raw_uid != uid:
            sent = await query.message.reply_text("❌ Este menú no es para ti.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        # set editing state
        if field in ("name", "description", "date", "url", "modifications"):
            context.user_data["editing"] = field
            sent = await query.message.reply_text(f"✏️ Escribe el nuevo valor para <b>{field}</b> (envíalo como texto).", parse_mode="HTML")
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        if field == "topic":
            sent = await query.message.reply_text("Selecciona el tema:", reply_markup=topics_keyboard_for_editing(uid))
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        if field == "photo":
            context.user_data["expect_photo"] = True
            context.user_data["editing_field_for"] = "photo"
            sent = await query.message.reply_text("📸 Envía la FOTO ahora (se reemplazará cualquier GIF que tuvieses).")
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        if field == "gif":
            context.user_data["expect_photo"] = True
            context.user_data["editing_field_for"] = "gif"
            sent = await query.message.reply_text("🎞 Envía el GIF ahora (reemplazará la foto si existe).")
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return

    if data.startswith("settopic:"):
        try:
            _, tid, raw_uid = data.split(":", 2)
            tid = int(tid); raw_uid = int(raw_uid)
        except Exception:
            sent = await query.message.reply_text("❌ Datos de callback inválidos.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        if raw_uid != uid:
            sent = await query.message.reply_text("❌ Este menú no es para ti.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        POST_DRAFTS.setdefault(uid, make_default_post())
        POST_DRAFTS[uid]["topic_id"] = tid
        sent = await query.message.reply_text(f"✅ Tema establecido: {POST_TOPICS.get(tid)}\nAhora puedes editar el resto del post.", reply_markup=edit_menu(uid))
        await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    if data.startswith("prepare_publish:"):
        try:
            _, raw_uid = data.split(":", 1)
            raw_uid = int(raw_uid)
        except Exception:
            sent = await query.message.reply_text("❌ Datos inválidos.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        if raw_uid != uid:
            sent = await query.message.reply_text("❌ Este menú no es para ti.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        sent = await query.message.reply_text("¿Seguro que quieres publicar este borrador?", reply_markup=publish_confirm_keyboard(uid))
        await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    if data.startswith("publish_yes:"):
        try:
            _, raw_uid = data.split(":", 1)
            raw_uid = int(raw_uid)
        except Exception:
            sent = await query.message.reply_text("❌ Datos inválidos.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        if raw_uid != uid:
            sent = await query.message.reply_text("❌ Este menú no es para ti.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        # publish the draft to STORAGE_CHAT_ID and remove draft
        draft = POST_DRAFTS.get(uid)
        if not draft:
            sent = await query.message.reply_text("❌ No hay borrador para publicar.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        caption = (
            f"<b>🌸 {escape_html(draft['name'])}</b>\n\n"
            f"💜 {escape_html(draft['description'])}\n\n"
            f"👤 <b>Autor:</b> Yamato\n"
            f"📚 <b>Tema:</b> {POST_TOPICS.get(draft.get('topic_id')) if draft.get('topic_id') else '—'}\n"
            f"📅 <b>Fecha:</b> {escape_html(draft['date'])}\n\n"
            f"🛠 <b>Modificaciones:</b>\n{escape_html(draft.get('modifications','—'))}"
        )
        kb = download_button_for_post(draft)
        try:
            # Ensure we always pass message_thread_id so message goes to correct topic (if present)
            thread_id = draft.get("topic_id")
            if draft.get("gif_id"):
                sent_post = await context.bot.send_animation(
                    chat_id=STORAGE_CHAT_ID,
                    animation=draft["gif_id"],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=kb,
                    message_thread_id=thread_id
                )
            elif draft.get("photo_id"):
                sent_post = await context.bot.send_photo(
                    chat_id=STORAGE_CHAT_ID,
                    photo=draft["photo_id"],
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=kb,
                    message_thread_id=thread_id
                )
            else:
                sent_post = await context.bot.send_message(
                    chat_id=STORAGE_CHAT_ID,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=kb,
                    message_thread_id=thread_id
                )
            # delete draft after publishing
            POST_DRAFTS.pop(uid, None)
            context.user_data.pop("backup", None)
            sent = await query.message.reply_text("✅ Publicado y borrador eliminado. ¡Listo!", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        except Exception as e:
            logger.exception("Error publicando: %s", e)
            sent = await query.message.reply_text("❌ Error al publicar. Revisa los permisos del bot.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    if data.startswith("publish_no:"):
        sent = await query.message.reply_text("❎ Publicación cancelada.", reply_markup=main_menu())
        await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    if data.startswith("restore_backup:"):
        try:
            _, raw_uid = data.split(":", 1)
            raw_uid = int(raw_uid)
        except Exception:
            sent = await query.message.reply_text("❌ Datos inválidos.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        if raw_uid != uid:
            sent = await query.message.reply_text("❌ Este menú no es para ti.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        backup = context.user_data.get("backup")
        if backup:
            POST_DRAFTS[uid] = copy.deepcopy(backup)
            sent = await query.message.reply_text("↩️ Restaurado a la versión anterior.", reply_markup=edit_menu(uid))
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        else:
            sent = await query.message.reply_text("❌ No hay copia de seguridad.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    if data.startswith("menu_back"):
        sent = await query.message.reply_text("Volviendo al menú principal.", reply_markup=main_menu())
        await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    sent = await query.message.reply_text("Operación no reconocida.", reply_markup=main_menu())
    await track_and_replace(context, uid, sent.chat.id, sent.message_id)


# ---------------- Photo / GIF handler ----------------

async def photo_or_gif_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    uid = msg.from_user.id

    # If it's expected as part of edit flow (photo or gif)
    if context.user_data.get("expect_photo"):
        field = context.user_data.get("editing_field_for", "photo")  # 'photo' or 'gif'
        POST_DRAFTS.setdefault(uid, make_default_post())
        # handle photo
        if msg.photo:
            # store highest resolution photo
            POST_DRAFTS[uid]["photo_id"] = msg.photo[-1].file_id
            # remove gif (option A: only one)
            POST_DRAFTS[uid]["gif_id"] = None
            context.user_data.pop("expect_photo", None)
            context.user_data.pop("editing_field_for", None)
            # delete user's message
            try:
                await msg.delete()
            except Exception:
                pass
            await cleanup_user_messages(context, uid)
            sent = await msg.reply_text("📸 Foto añadida al borrador.", reply_markup=edit_menu(uid))
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        # handle GIF (animation or document with mime image/gif)
        anim = msg.animation or (msg.document if msg.document and msg.document.mime_type == "image/gif" else None)
        if anim:
            POST_DRAFTS[uid]["gif_id"] = anim.file_id
            POST_DRAFTS[uid]["photo_id"] = None  # option A: gif replaces photo
            context.user_data.pop("expect_photo", None)
            context.user_data.pop("editing_field_for", None)
            try:
                await msg.delete()
            except Exception:
                pass
            await cleanup_user_messages(context, uid)
            sent = await msg.reply_text("🎞 GIF añadido al borrador (reemplazó la foto si existía).", reply_markup=edit_menu(uid))
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            return
        # not accepted
        sent = await msg.reply_text("❌ Envía una FOTO o un GIF válido.", reply_markup=edit_menu(uid))
        await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

    # If it's expected for ID extraction
    if context.user_data.get("expect_id"):
        # return file_id and unique id for the media sent
        if msg.photo:
            pid = msg.photo[-1].file_id
            puid = msg.photo[-1].file_unique_id
            sent = await msg.reply_text(f"📸 Photo file_id:\n{pid}\n\nfile_unique_id:\n{puid}", parse_mode="HTML")
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            context.user_data.pop("expect_id", None)
            return
        anim = msg.animation or (msg.document if msg.document and msg.document.mime_type == "image/gif" else None)
        if anim:
            sent = await msg.reply_text(f"🎞 GIF file_id:\n{anim.file_id}\n\nfile_unique_id:\n{anim.file_unique_id}", parse_mode="HTML")
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
            context.user_data.pop("expect_id", None)
            return
        sent = await msg.reply_text("❌ Envía una FOTO o un GIF para obtener su ID.", parse_mode="HTML")
        await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        return

# ---------------- Media handlers (GLOBAL QUEUE) ----------------

async def _process_user_queue(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int):
    USER_QUEUE_TIMER.pop(user_id, None)  # timer consumed
    msgs = USER_MEDIA_QUEUE.pop(user_id, [])
    if not msgs:
        return

    USER_PROCESSING[user_id] = True
    total = len(msgs)
    copied = 0
    failed = []

    # send single progress message
    progress_msg = None
    try:
        progress_msg = await context.bot.send_message(chat_id=chat_id, text=make_progress_bar(0))
        await track_and_replace(context, user_id, progress_msg.chat.id, progress_msg.message_id)
    except Exception:
        progress_msg = None

    try:
        for m in msgs:
            try:
                # Only copy audio/voice documents
                media_obj = m.audio or m.voice
                if not media_obj:
                    # treat as failed
                    failed.append(m)
                    try:
                        await m.reply_text("❌ Este archivo no es audio y no se guardó.")
                    except Exception:
                        pass
                        # continue without deleting
                else:
                    await context.bot.copy_message(chat_id=STORAGE_CHAT_ID, from_chat_id=m.chat.id, message_id=m.message_id, message_thread_id=MUSICAS_TOPIC_ID)
                    TRACKED_MEDIA[m.message_id] = getattr(media_obj, "file_id", None)
                    try:
                        await context.bot.delete_message(chat_id=m.chat.id, message_id=m.message_id)
                    except Exception:
                        pass
                    copied += 1
            except Exception as e:
                logger.exception("Error copying media message: %s", e)
                failed.append(m)
            # update progress bar
            pct = int((copied / total) * 100) if total else 100
            if progress_msg:
                try:
                    await context.bot.edit_message_text(text=make_progress_bar(pct), chat_id=progress_msg.chat.id, message_id=progress_msg.message_id)
                except Exception:
                    pass
            await asyncio.sleep(0.12)
    finally:
        # finalize progress and remove it (ensure removal)
        if progress_msg:
            try:
                await context.bot.edit_message_text(text=make_progress_bar(100), chat_id=progress_msg.chat.id, message_id=progress_msg.message_id)
            except Exception:
                pass
            await asyncio.sleep(0.25)
            try:
                await context.bot.delete_message(chat_id=progress_msg.chat.id, message_id=progress_msg.message_id)
            except Exception:
                pass

        saved_count = copied
        try:
            if failed:
                sent = await context.bot.send_message(chat_id=chat_id, text=f"🎧 Se guardaron {saved_count} canciones. ❌ {len(failed)} fallaron (quedan en el chat).", parse_mode="HTML")
                await track_and_replace(context, user_id, sent.chat.id, sent.message_id)
            else:
                sent = await context.bot.send_message(chat_id=chat_id, text=f"🎧✨ 🎞💜 Canciones guardadas en <b>Músicas</b> ({saved_count} archivos).", parse_mode="HTML")
                await track_and_replace(context, user_id, sent.chat.id, sent.message_id)
        except Exception:
            pass

        USER_PROCESSING[user_id] = False


async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    # only accept private messages to save music
    if msg.chat.type != "private":
        return
    # accept only audio or voice
    media = msg.audio or msg.voice
    if not media:
        try:
            sent = await msg.reply_text("❌ Solo puedo guardar archivos de audio. Envía un archivo de audio (mp3, m4a, ogg, voice).")
            await track_and_replace(context, msg.from_user.id, sent.chat.id, sent.message_id)
        except Exception:
            pass
        return

    uid = msg.from_user.id
    chat_id = msg.chat.id

    # If user is currently processing a batch, notify
    if USER_PROCESSING.get(uid):
        try:
            sent = await msg.reply_text("⏳ Estoy guardando tu lote actual. Por favor espera a que termine antes de enviar más archivos.")
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        except Exception:
            pass
        return

    # Append to user's global queue
    QUEUE = USER_MEDIA_QUEUE.setdefault(uid, [])
    QUEUE.append(msg)

    # If there's already a timer scheduled, leave it (it will process when it fires)
    if uid in USER_QUEUE_TIMER:
        return

    # Otherwise schedule processing after 2 seconds
    async def _delayed_process(u_id, c_id):
        await asyncio.sleep(2.0)
        try:
            await _process_user_queue(context, u_id, c_id)
        except Exception as e:
            logger.exception("Error in delayed processing: %s", e)

    USER_QUEUE_TIMER[uid] = asyncio.create_task(_delayed_process(uid, chat_id))


# ---------------- Text handler for editing fields ----------------

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "editing" not in context.user_data:
        return
    field = context.user_data.get("editing")
    uid = update.effective_user.id
    if not update.message:
        return

    # delete user's message to keep chat clean
    try:
        await update.message.delete()
    except Exception:
        pass

    POST_DRAFTS.setdefault(uid, make_default_post())
    draft = POST_DRAFTS[uid]
    text = update.message.text or ""

    if field == "name":
        draft["name"] = text.strip()
    elif field == "description":
        draft["description"] = text.rstrip()
    elif field == "date":
        draft["date"] = text.strip()
    elif field == "url":
        draft["url"] = text.strip()
    elif field == "modifications":
        draft["modifications"] = text.rstrip()
    else:
        try:
            sent = await update.message.reply_text("❌ Campo desconocido.", reply_markup=main_menu())
            await track_and_replace(context, uid, sent.chat.id, sent.message_id)
        except Exception:
            pass
        context.user_data.pop("editing", None)
        return

    # done editing - full cleanup and show only clean messages
    await cleanup_user_messages(context, uid)
    sent = await update.effective_chat.send_message("✏️🌸 Cambios guardados.\nAquí tienes el menú de edición para seguir:", reply_markup=edit_menu(uid))
    await track_and_replace(context, uid, sent.chat.id, sent.message_id)
    context.user_data.pop("editing", None)

# ---------------- Build & Run ----------------

def build_app():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ID", cmd_id))  # only command left available
    app.add_handler(CallbackQueryHandler(menu_callback))
    # photo and GIF handler (for both edit flow and ID extraction)
    app.add_handler(MessageHandler((filters.PHOTO | filters.ANIMATION | filters.Document.GIF), photo_or_gif_handler))
    # media: only audio and voice
    app.add_handler(MessageHandler((filters.AUDIO | filters.VOICE), media_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # schedule periodic auto-clean job (optional, keeps working if job-queue installed)
    try:
        job_queue = app.job_queue
        # If available, run auto_cleanup_job periodically
        job_queue.run_repeating(lambda ctx: asyncio.create_task(auto_cleanup_job(ctx)), interval=AUTOCLEAN_INTERVAL_SECONDS, first=AUTOCLEAN_INTERVAL_SECONDS)
    except Exception:
        # ignore if job_queue not available — option 2 does not require it
        pass

    return app

if __name__ == "__main__":
    app = build_app()
    app.run_polling()