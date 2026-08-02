"""Telegram bot handlers — commands and message processing."""
import os
import re
import logging
import asyncio
from telegram import Update, BotCommand
from telegram.ext import ContextTypes
from telegram.constants import ParseMode, ChatAction

from config import ALLOWED_USERS, AUTO_CLEANUP
from downloader import detect_source, download, cleanup, get_file_info

logger = logging.getLogger(__name__)

# Track active downloads per user
_active_downloads: dict[int, asyncio.Task] = {}

# URL regex for detecting links in messages
URL_RE = re.compile(
    r"(https?://[^\s<>\"']+|magnet:\?[^\s<>\"']+)",
    re.IGNORECASE,
)

SOURCE_EMOJI = {
    "direct": "🔗",
    "magnet": "🧲",
    "torrent": "📄",
    "youtube": "📺",
    "gdrive": "📁",
}


def _check_access(user_id: int) -> bool:
    """Check if user is allowed (empty ALLOWED_USERS = open to all)."""
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if not _check_access(update.effective_user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    
    await update.message.reply_text(
        "🤖 <b>Leecher Bot</b>\n\n"
        "Send me a URL and I'll download it for you!\n\n"
        "<b>Supported sources:</b>\n"
        "🔗 Direct download links\n"
        "🧲 Magnet links\n"
        "📄 Torrent file URLs\n"
        "📺 YouTube / Aparat videos\n"
        "📁 Google Drive links\n\n"
        "Just paste any link and I'll handle the rest! ⬇️",
        parse_mode=ParseMode.HTML,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not _check_access(update.effective_user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    
    await update.message.reply_text(
        "📖 <b>How to use:</b>\n\n"
        "1️⃣ Send any URL/link\n"
        "2️⃣ I'll detect the source and download\n"
        "3️⃣ File will be sent to you!\n\n"
        "<b>Examples:</b>\n"
        "• <code>https://example.com/file.zip</code>\n"
        "• <code>magnet:?xt=urn:btih:...</code>\n"
        "• <code>https://youtube.com/watch?v=...</code>\n"
        "• <code>https://drive.google.com/file/d/...</code>\n\n"
        "<b>Commands:</b>\n"
        "/start — Welcome message\n"
        "/help — This help\n"
        "/cancel — Cancel active download\n\n"
        "<b>Tip:</b> Send multiple links at once!",
        parse_mode=ParseMode.HTML,
    )


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cancel command."""
    user_id = update.effective_user.id
    task = _active_downloads.get(user_id)
    if task and not task.done():
        task.cancel()
        _active_downloads.pop(user_id, None)
        await update.message.reply_text("❌ Download cancelled.")
    else:
        await update.message.reply_text("No active download to cancel.")


async def _process_download(update: Update, url: str) -> None:
    """Process a single URL download."""
    user_id = update.effective_user.id
    source_type = detect_source(url)
    emoji = SOURCE_EMOJI.get(source_type, "🔗")
    
    status_msg = await update.message.reply_text(
        f"{emoji} <b>Detecting source...</b>\n"
        f"<code>{url[:100]}</code>",
        parse_mode=ParseMode.HTML,
    )
    
    file_path = None
    try:
        # Show downloading status
        await status_msg.edit_text(
            f"{emoji} <b>Downloading</b> ({source_type})...\n"
            f"<code>{url[:100]}</code>\n\n"
            f"⏳ Please wait...",
            parse_mode=ParseMode.HTML,
        )
        await update.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
        
        # Download
        file_path, filename, source_type = await download(url)
        file_info = get_file_info(file_path)
        
        # Update status
        await status_msg.edit_text(
            f"{emoji} <b>Uploading:</b> <code>{filename}</code>\n"
            f"📏 Size: {_format_size(file_info['size'])}\n"
            f"📦 Source: {source_type}",
            parse_mode=ParseMode.HTML,
        )
        await update.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
        
        # Send the file
        with open(file_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption=(
                    f"{emoji} <b>{filename}</b>\n"
                    f"📏 {_format_size(file_info['size'])} | {source_type}"
                ),
                parse_mode=ParseMode.HTML,
            )
        
        # Success message
        await status_msg.edit_text(
            f"✅ <b>Done!</b> <code>{filename}</code>",
            parse_mode=ParseMode.HTML,
        )
    
    except asyncio.CancelledError:
        await status_msg.edit_text("❌ Download cancelled.")
        if file_path:
            cleanup(file_path)
        return
    
    except TimeoutError:
        await status_msg.edit_text(
            f"⏰ <b>Download timed out</b>\n"
            f"The source might be slow or unavailable.",
            parse_mode=ParseMode.HTML,
        )
    
    except ValueError as e:
        await status_msg.edit_text(
            f"❌ <b>Error:</b> {e}",
            parse_mode=ParseMode.HTML,
        )
    
    except Exception as e:
        logger.exception(f"Download failed for {url}")
        await status_msg.edit_text(
            f"❌ <b>Download failed</b>\n<code>{str(e)[:200]}</code>",
            parse_mode=ParseMode.HTML,
        )
    
    finally:
        _active_downloads.pop(user_id, None)
        if file_path and AUTO_CLEANUP:
            cleanup(file_path)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any message — detect URLs and download."""
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    if not _check_access(user_id):
        return
    
    text = update.message.text.strip()
    urls = URL_RE.findall(text)
    
    if not urls:
        return  # Not a URL, ignore
    
    # Process each URL
    for url in urls:
        # Check if user already has an active download
        if user_id in _active_downloads and not _active_downloads[user_id].done():
            await update.message.reply_text(
                "⏳ You already have an active download. Send /cancel to stop it first."
            )
            continue
        
        # Start download in background
        task = asyncio.create_task(_process_download(update, url))
        _active_downloads[user_id] = task


async def post_init(application) -> None:
    """Set bot commands after initialization."""
    await application.bot.set_my_commands([
        BotCommand("start", "Welcome message"),
        BotCommand("help", "How to use"),
        BotCommand("cancel", "Cancel active download"),
    ])
