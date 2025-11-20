import os
import time
import logging
import json
import asyncio
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Chat,
    InlineQueryResultArticle, InputTextMessageContent
)
from pyrogram.enums import ChatType

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

TOPICS = {
    "APKS": 5,
    "GTA+AML": 8,
    "Silksong": 7,
    "Hollow Knight": 6,
    "Músicas": 2
}

POST_DRAFTS = {}

MUSIC_QUEUE = {}

MEDIA_GROUP_SENT = {}

DEFAULT_POST_STRUCTURE = {
    "name": '<<< NOMBRE DEL POST AQUÍ >>>',
    "description": '<<< DESCRIPCIÓN AQUÍ >>>',
    "date": datetime.now().strftime("%Y-%m-%d"),
    "url": 'https://t.me/',
    "photo_id": None,
    "modifications": '• No hay modificaciones especificadas.',
    "thread_id": None
}

def load_config():
    config = {}
    required_keys = ["TELEGRAM_BOT_TOKEN", "API_ID", "API_HASH", "STORAGE_CHAT_ID"]

    for key in required_keys:
        value = os.getenv(key)
        if not value:
            print(f"\n⚠️ ERROR: La variable de entorno '{key}' no está configurada.")
            print("Por favor, configura las variables de entorno en Replit Secrets.")
            exit(1)
        config[key] = value

    try:
        config['API_ID'] = int(config['API_ID'])
        config['STORAGE_CHAT_ID'] = int(config['STORAGE_CHAT_ID'])
    except ValueError as e:
        print(f"\n⚠️ ERROR: API_ID y STORAGE_CHAT_ID deben ser números enteros.")
        print(f"Detalle: {e}")
        exit(1)
    
    return config

CONFIG = load_config()

app_tg = Client(
    "yamato_cloud_bot",
    bot_token=CONFIG['TELEGRAM_BOT_TOKEN'],
    api_id=CONFIG['API_ID'],
    api_hash=CONFIG['API_HASH']
)

def get_post_preview_text(draft_data: dict) -> str:
    """Crea el texto final del post con formato limpio."""
    return (
        f"💜 | **{draft_data['name']}**\n"
        f"🖤 | *{draft_data['description']}*\n"
        f"💜 | Fecha de Publicación: `{draft_data['date']}`\n\n"
        f"✨ *Modificaciones:*\n"
        f"_{draft_data.get('modifications', '• No hay modificaciones especificadas.')}_\n\n"
        f"ID del Tema: `{draft_data.get('thread_id', 'NO DEFINIDO')}`"
    )

def get_post_keyboard(url: str) -> InlineKeyboardMarkup:
    """Crea el botón de DESCARGA."""
    keyboard = [[InlineKeyboardButton("💜. DESCARGA.🖤", url=url)]]
    return InlineKeyboardMarkup(keyboard)

def get_topic_list_text() -> str:
    """Genera la lista de temas para /temas."""
    text = "📁 **Temas disponibles:**\n\n"
    for name, tid in TOPICS.items():
        text += f"💜 {name} » `{tid}`\n"
    text += "\n_Usa el ID en /editarpost y /postear_"
    return text

@app_tg.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    """Mensaje de bienvenida."""
    user_name = message.from_user.first_name
    await message.reply_text(f"Hola {user_name} soy Yamato 💜 usa /help para tener más información.")

@app_tg.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    """Muestra la ayuda de comandos."""
    await message.reply_text(
        "💜 **Comandos disponibles:**\n\n"
        "📁 `/temas` - Ver temas\n"
        "✏️ `/editarpost [ID] [campo] [valor]` - Editar borrador\n"
        "👁️ `/verpost` - Previsualizar\n"
        "📤 `/postear` - Publicar\n"
        "🆔 `/ID` - Ver IDs\n\n"
        "✨ **Tips:**\n"
        "📸 Envía fotos para obtener su ID\n"
        "🎶 Envía música para guardarla"
    )

@app_tg.on_message(filters.command("temas"))
async def topics_command(client: Client, message: Message):
    """Muestra la lista de temas existentes."""
    await message.reply_text(get_topic_list_text())

@app_tg.on_message(filters.command("ID"))
async def get_id_command(client: Client, message: Message):
    """Devuelve el ID del chat y del tema (si aplica)."""
    text = f"🆔 **IDs:**\n"
    text += f"💬 Chat: `{message.chat.id}`\n"

    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        topic_id = None
        
        if hasattr(message, 'message_thread_id') and message.message_thread_id:
            topic_id = message.message_thread_id
        elif hasattr(message, 'reply_to_message_id') and message.reply_to_message_id:
            topic_id = message.reply_to_message_id
        
        if topic_id:
            text += f"📁 Tema: `{topic_id}`"
        else:
            text += f"\n_Usa /ID dentro de un tema para ver su ID_"
    
    await message.reply_text(text)


@app_tg.on_message(filters.photo & filters.private)
async def get_photo_id(client: Client, message: Message):
    """Devuelve el ID de la foto para usarlo en /editarpost."""
    photo_id = message.photo.file_id
    await message.reply_text(
        f"📸 **ID de imagen:**\n`{photo_id}`\n\n"
        f"_Úsalo en: `/editarpost [ID] photo_id {photo_id}`_"
    )


@app_tg.on_message(filters.command("editarpost") & filters.private)
async def edit_post_command(client: Client, message: Message):
    """Edita los valores del borrador de post."""
    user_id = message.from_user.id
    parts = message.text.split(maxsplit=3)
    
    if user_id not in POST_DRAFTS:
        POST_DRAFTS[user_id] = DEFAULT_POST_STRUCTURE.copy()

    draft_data = POST_DRAFTS[user_id]

    if len(parts) < 3:
        text = "📝 **Borrador actual:**\n"
        for key, value in draft_data.items():
            text += f"💜 {key.replace('_', ' ').title()}: `{value}`\n"
        
        text += "\n**Ejemplos:**\n"
        text += "`/editarpost 5 name Mi App`\n"
        text += "`/editarpost 7 url https://link.dev`"
        
        await message.reply_text(text)
        return

    try:
        topic_id = int(parts[1])
        field = parts[2].lower()
        value = parts[3] if len(parts) == 4 else ""

    except ValueError:
        await message.reply_text("❌ El ID debe ser un número")
        return
    except IndexError:
        await message.reply_text("❌ Faltan parámetros\n_Usa: `/editarpost [ID] [campo] [valor]`_")
        return
    
    if topic_id not in TOPICS.values():
        await message.reply_text("❌ ID no encontrado. Usa `/temas`")
        return
    
    if field not in DEFAULT_POST_STRUCTURE:
        await message.reply_text(f"❌ Campo '{field}' no válido")
        return

    draft_data[field] = value
    draft_data['thread_id'] = topic_id

    await message.reply_text(f"✅ **Actualizado** 💜\n{field.replace('_', ' ').title()}: `{value}`")


@app_tg.on_message(filters.command("verpost") & filters.private)
async def preview_post_command(client: Client, message: Message):
    """Muestra una previsualización del post actual."""
    user_id = message.from_user.id
    
    if user_id not in POST_DRAFTS or not POST_DRAFTS[user_id].get('thread_id'):
        await message.reply_text("❌ Sin borrador activo\n_Usa `/editarpost` primero_")
        return

    draft_data = POST_DRAFTS[user_id]
    caption = get_post_preview_text(draft_data)
    reply_markup = get_post_keyboard(draft_data['url'])
    
    if draft_data['photo_id']:
        try:
            await client.send_photo(
                chat_id=message.chat.id,
                photo=draft_data['photo_id'],
                caption=caption,
                reply_markup=reply_markup
            )
        except Exception as e:
            await message.reply_text(f"❌ Error: ID de imagen inválido")
    else:
        await message.reply_text(caption, reply_markup=reply_markup)


@app_tg.on_message(filters.command("postear") & filters.private)
async def post_command(client: Client, message: Message):
    """Publica el borrador final en el tema especificado."""
    user_id = message.from_user.id
    
    if user_id not in POST_DRAFTS or not POST_DRAFTS[user_id].get('thread_id'):
        await message.reply_text("❌ Sin borrador activo")
        return

    draft_data = POST_DRAFTS[user_id]
    topic_id = draft_data.get('thread_id')
    
    if not topic_id:
        await message.reply_text("❌ Sin tema asignado")
        return

    caption = get_post_preview_text(draft_data)
    reply_markup = get_post_keyboard(draft_data['url'])
    
    try:
        if draft_data['photo_id']:
            await client.send_photo(
                chat_id=CONFIG['STORAGE_CHAT_ID'],
                photo=draft_data['photo_id'],
                caption=caption,
                reply_markup=reply_markup,
                reply_to_message_id=topic_id
            )
        else:
            await client.send_message(
                chat_id=CONFIG['STORAGE_CHAT_ID'],
                text=caption,
                reply_markup=reply_markup,
                reply_to_message_id=topic_id
            )
        
        topic_name = next((name for name, tid in TOPICS.items() if tid == topic_id), "tema")
        del POST_DRAFTS[user_id]
        await message.reply_text(f"✅ **Publicado en {topic_name}** 💜")

    except Exception as e:
        await message.reply_text(f"❌ Error al publicar\n_Verifica permisos del bot_")


@app_tg.on_message((filters.audio | filters.document) & filters.private)
async def music_handler(client: Client, message: Message):
    """Captura archivos de música y pregunta al usuario si desea guardarlos."""
    
    logger.info(f"Mensaje recibido - Audio: {message.audio is not None}, Document: {message.document is not None}")
    
    if not (message.audio or (message.document and message.document.mime_type and 'audio' in message.document.mime_type)):
        logger.info("No es un archivo de audio, ignorando...")
        return

    user_id = message.from_user.id
    logger.info(f"Usuario {user_id} envió música")
    
    if user_id not in MUSIC_QUEUE:
        MUSIC_QUEUE[user_id] = []
    
    media_group_id = message.media_group_id
    
    if media_group_id:
        logger.info(f"Mensaje pertenece al grupo de medios: {media_group_id}")
        
        if media_group_id in MEDIA_GROUP_SENT:
            logger.info(f"Ya se envió confirmación para el grupo {media_group_id}, solo agregando a la cola")
            MUSIC_QUEUE[user_id].append(message.id)
            return
        else:
            MEDIA_GROUP_SENT[media_group_id] = True
            MUSIC_QUEUE[user_id].append(message.id)
            await asyncio.sleep(1.5)
    else:
        MUSIC_QUEUE[user_id].append(message.id)
        await asyncio.sleep(0.5)
    
    logger.info(f"Mensaje {message.id} agregado a la cola. Total: {len(MUSIC_QUEUE[user_id])}")
    
    num_files = len(MUSIC_QUEUE[user_id])
    
    if num_files == 0:
        return

    question = f"🎶 {num_files} canción(es). ¿Guardar en Músicas?"
    
    keyboard = [[
        InlineKeyboardButton("✅ Sí", callback_data=f"save_music_{user_id}"),
        InlineKeyboardButton("❌ No", callback_data=f"cancel_music_{user_id}")
    ]]
    
    logger.info("Enviando pregunta de confirmación...")
    await message.reply_text(
        question, 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        reply_to_message_id=message.id
    )


@app_tg.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    """Maneja los botones interactivos, especialmente para guardar música."""
    data = callback_query.data
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    
    logger.info(f"Callback recibido: {data} de usuario {user_id}")
    
    if data.startswith("save_music_") and user_id in MUSIC_QUEUE:
        logger.info(f"Guardando {len(MUSIC_QUEUE[user_id])} archivos para usuario {user_id}")
        await callback_query.edit_message_text("⏳ Guardando...")
        
        music_topic_id = TOPICS["Músicas"]
        message_ids_to_delete = []

        try:
            logger.info(f"ID del chat de almacenamiento: {CONFIG['STORAGE_CHAT_ID']}, Topic ID: {music_topic_id}")
            
            for msg_id in MUSIC_QUEUE[user_id]:
                logger.info(f"Procesando mensaje {msg_id}")
                
                logger.info(f"Copiando mensaje {msg_id} al chat {CONFIG['STORAGE_CHAT_ID']} en tema {music_topic_id}")
                
                await client.copy_message(
                    chat_id=CONFIG['STORAGE_CHAT_ID'],
                    from_chat_id=chat_id,
                    message_id=msg_id,
                    reply_to_message_id=music_topic_id
                )
                
                message_ids_to_delete.append(msg_id)
                logger.info(f"Mensaje {msg_id} copiado exitosamente")
                
            logger.info(f"Eliminando {len(message_ids_to_delete)} mensajes del chat privado")
            await client.delete_messages(chat_id, message_ids_to_delete)
            
            await callback_query.message.delete()
            
            await client.send_message(
                chat_id=chat_id, 
                text=f"✅ {len(message_ids_to_delete)} archivo(s) en Músicas 💜"
            )
            logger.info("Guardado completado exitosamente")
            
        except Exception as e:
            logger.error(f"Error al guardar música: {e}", exc_info=True)
            await callback_query.edit_message_text(f"❌ Error al guardar\n_Verifica permisos del bot_")

        finally:
            if user_id in MUSIC_QUEUE:
                del MUSIC_QUEUE[user_id]
            MEDIA_GROUP_SENT.clear()
            logger.info("Cola de música limpiada")


    elif data.startswith("cancel_music_") and user_id in MUSIC_QUEUE:
        await callback_query.message.delete()
        
        await client.send_message(
            chat_id=chat_id, 
            text="❌ Cancelado"
        )
        del MUSIC_QUEUE[user_id]
        MEDIA_GROUP_SENT.clear()

    else:
        await callback_query.answer("❌ Esta acción no está disponible.", show_alert=True)


if __name__ == "__main__":
    print("🚀 Bot Yamato 💜 iniciado...")
    print("✅ Configuración y temas cargados con éxito.")
    app_tg.run()
