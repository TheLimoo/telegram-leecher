"""Telegram bot handlers — commands and message processing."""
import os
import re
import logging
import asyncio
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode, ChatAction

from config import ALLOWED_USERS, AUTO_CLEANUP, LOCAL_API_URL
from downloader import detect_source, download, cleanup, get_file_info, get_youtube_formats, _format_size

logger = logging.getLogger(__name__)

# Track active downloads per user
_active_downloads: dict[int, asyncio.Task] = {}
# Track quality preferences per user
_youtube_quality: dict[int, str] = {}

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
    "instagram": "📸",
    "gdrive": "📁",
}


def _check_access(user_id: int) -> bool:
    """Check if user is allowed (empty ALLOWED_USERS = open to all)."""
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


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
        "📸 Instagram reels/posts\n"
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
        "• <code>https://instagram.com/reel/...</code>\n"
        "• <code>https://drive.google.com/file/d/...</code>\n\n"
        "<b>Commands:</b>\n"
        "/start — Welcome message\n"
        "/help — This help\n"
        "/cancel — Cancel active download\n"
        "/quality <720p|480p|360p|best|worst> — Set YouTube quality\n\n"
        "<b>Tip:</b> Send multiple links at once!",
        parse_mode=ParseMode.HTML,
    )


async def quality_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set YouTube download quality."""
    if not _check_access(update.effective_user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    
    if not context.args:
        current = _youtube_quality.get(update.effective_user.id, "best")
        await update.message.reply_text(
            f"📺 <b>Current YouTube quality:</b> <code>{current}</code>\n\n"
            "Set quality with:\n"
            "/quality best — Highest available (default)\n"
            "/quality 720p — 720p HD\n"
            "/quality 480p — 480p\n"
            "/quality 360p — 360p\n"
            "/quality worst — Lowest available",
            parse_mode=ParseMode.HTML,
        )
        return
    
    quality = context.args[0].lower()
    valid_qualities = ["best", "720p", "480p", "360p", "worst"]
    
    if quality not in valid_qualities:
        await update.message.reply_text(
            f"❌ <b>Invalid quality!</b>\n\n"
            f"Valid options: {', '.join(valid_qualities)}",
            parse_mode=ParseMode.HTML,
        )
        return
    
    _youtube_quality[update.effective_user.id] = quality
    await update.message.reply_text(
        f"✅ <b>YouTube quality set to:</b> <code>{quality}</code>",
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


async def test_api_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Test if self-hosted Bot API is working."""
    if not _check_access(update.effective_user.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    
    if LOCAL_API_URL:
        import aiohttp
        try:
            api_base = LOCAL_API_URL.rstrip('/')
            test_url = f"{api_base}/bot{context.bot.token}/getMe"
            async with aiohttp.ClientSession() as session:
                async with session.post(test_url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        await update.message.reply_text(
                            "✅ <b>Self-hosted Bot API is running!</b>\n"
                            f"📍 URL: <code>{api_base}</code>\n"
                            f"🤖 Bot: @{data.get('result', {}).get('username', 'unknown')}\n"
                            "📤 Upload limit: <b>2 GB</b>",
                            parse_mode=ParseMode.HTML,
                        )
                    else:
                        text = await resp.text()
                        await update.message.reply_text(
                            f"⚠️ Bot API responded with status {resp.status}\n<code>{text[:200]}</code>",
                            parse_mode=ParseMode.HTML,
                        )
        except Exception as e:
            await update.message.reply_text(
                f"❌ <b>Bot API not reachable:</b>\n<code>{e}</code>\n\n"
                "Check if TELEGRAM_API_ID/HASH are set correctly.",
                parse_mode=ParseMode.HTML,
            )
    else:
        await update.message.reply_text(
            "ℹ️ <b>Using standard Telegram Bot API</b>\n"
            "📍 URL: <code>https://api.telegram.org</code>\n"
            "📤 Upload limit: <b>50 MB</b>\n\n"
            "To enable unlimited uploads, set TELEGRAM_API_ID and TELEGRAM_API_HASH.",
            parse_mode=ParseMode.HTML,
        )


async def show_quality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, formats: list[dict]) -> None:
    """Show inline keyboard for quality selection."""
    if not formats:
        await update.message.reply_text("❌ No formats available for this video.")
        return
    
    keyboard = []
    for fmt in formats:
        btn_text = f"{fmt['height']}p - {fmt['filesize_str']} ({fmt['ext']})"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"quality:{fmt['format_id']}")])
    
    # Add best/worst options
    keyboard.append([
        InlineKeyboardButton("🎬 Best quality", callback_data="quality:best"),
        InlineKeyboardButton("📉 Worst quality", callback_data="quality:worst")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"📺 <b>Select YouTube quality:</b>\n\n"
        f"<code>{url[:80]}</code>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
    )


async def handle_youtube_quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle quality selection callback."""
    query = update.callback_query
    if not query:
        return
    
    await query.answer()
    
    if not _check_access(query.from_user.id):
        await query.edit_message_text("⛔ Access denied.")
        return
    
    callback_data = query.data
    if not callback_data or not callback_data.startswith("quality:"):
        return
    
    quality = callback_data.split(":")[1]
    url = context.user_data.get("pending_url")
    
    if not url:
        await query.edit_message_text("❌ Download session expired.")
        return
    
    # Remove quality selection message
    try:
        await query.delete_message()
    except Exception:
        pass
    
    # Start download with selected quality
    user_id = query.from_user.id
    source_type = detect_source(url)
    emoji = SOURCE_EMOJI.get(source_type, "🔗")
    
    status_msg = await query.message.reply_text(
        f"{emoji} <b>Downloading</b> ({source_type})...\n"
        f"<code>{url[:100]}</code>\n\n"
        f"⏳ Please wait...",
        parse_mode=ParseMode.HTML,
    )
    
    file_path = None
    try:
        await query.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
        
        # Download with selected quality
        file_path, filename, source_type = await download(url, quality=quality)
        file_info = get_file_info(file_path)
        
        # Update status
        await status_msg.edit_text(
            f"{emoji} <b>Uploading:</b> <code>{filename}</code>\n"
            f"📏 Size: {_format_size(file_info['size'])}\n"
            f"📦 Source: {source_type}",
            parse_mode=ParseMode.HTML,
        )
        await query.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
        
        # Send the file
        with open(file_path, "rb") as f:
            await query.message.reply_document(
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


async def _process_download(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, quality: str = "best") -> None:
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
        # For YouTube, show quality selection first
        if source_type == "youtube":
            # Get available formats
            await status_msg.edit_text(
                f"📺 <b>Getting video info...</b>\n"
                f"<code>{url[:100]}</code>",
                parse_mode=ParseMode.HTML,
            )
            formats = await get_youtube_formats(url)
            
            # If no formats available, proceed with default download
            if not formats:
                logger.info(f"No formats available, using default download for {url}")
                # Fall through to normal download
            else:
                # Show quality selection
                keyboard = []
                for fmt in formats:
                    btn_text = f"{fmt['height']}p - {fmt['filesize_str']} ({fmt['ext']})"
                    keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"quality:{fmt['format_id']}")])
                
                # Add best/worst options
                keyboard.append([
                    InlineKeyboardButton("🎬 Best", callback_data="quality:best"),
                    InlineKeyboardButton("📉 Worst", callback_data="quality:worst")
                ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await status_msg.edit_text(
                    f"📺 <b>Select YouTube quality:</b>\n\n"
                    f"<code>{url[:80]}</code>",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML,
                )
                
                # Store pending download for callback
                context.user_data["pending_url"] = url
                return
        
        # Show downloading status
        await status_msg.edit_text(
            f"{emoji} <b>Downloading</b> ({source_type})...\n"
            f"<code>{url[:100]}</code>\n\n"
            f"⏳ Please wait...",
            parse_mode=ParseMode.HTML,
        )
        await update.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
        
        # Download
        file_path, filename, source_type = await download(url, quality=quality)
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
    from bot import record_activity
    
    if not update.message or not update.message.text:
        return
    
    record_activity()  # Record user activity
    
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
        task = asyncio.create_task(_process_download(update, context, url))
        _active_downloads[user_id] = task


async def post_init(application) -> None:
    """Set bot commands after initialization."""
    # Add quality selection callback handler
    application.add_handler(CallbackQueryHandler(handle_youtube_quality_callback, pattern="^quality:"))
    
    await application.bot.set_my_commands([
        BotCommand("start", "Welcome message"),
        BotCommand("help", "How to use"),
        BotCommand("cancel", "Cancel active download"),
        BotCommand("quality", "Set YouTube quality"),
        BotCommand("testapi", "Test self-hosted Bot API"),
    ])
