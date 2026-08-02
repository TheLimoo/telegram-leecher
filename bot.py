#!/usr/bin/env python3
"""Telegram Leecher Bot — main entry point.

Supports:
- Polling mode (local dev)
- Webhook mode (production on Render/Railway)
- Self-hosted Bot API (removes 50MB upload limit) - uses local_mode
"""
import logging
import os
import sys
import time

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from config import BOT_TOKEN, WEBHOOK_URL, PORT, LOCAL_API_URL, DOWNLOAD_DIR
from handlers import start_cmd, help_cmd, cancel_cmd, handle_message, post_init

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("=== Telegram Leecher Bot Starting ===")
    logger.info(f"PORT: {PORT}")
    logger.info(f"WEBHOOK_URL: {WEBHOOK_URL or 'not set (polling mode)'}")
    logger.info(f"LOCAL_API_URL: {LOCAL_API_URL or 'not set (standard API)'}")
    logger.info(f"DOWNLOAD_DIR: {DOWNLOAD_DIR}")
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set! Set it in environment or .env file.")
        sys.exit(1)

    # Ensure download directory exists
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # Build application
    # Use local_mode for self-hosted Bot API (properly handles token in URL)
    if LOCAL_API_URL:
        logger.info(f"Using self-hosted Bot API (local_mode=True)")
        builder = ApplicationBuilder().token(BOT_TOKEN).local_mode(True)
    else:
        logger.info("Using standard api.telegram.org (50MB limit)")
        builder = ApplicationBuilder().token(BOT_TOKEN)

    try:
        app = builder.build()
    except Exception as e:
        logger.error(f"Failed to build application: {e}")
        sys.exit(1)

    # Register handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Post-init: set bot commands
    app.post_init = post_init

    # Start the bot
    if WEBHOOK_URL:
        # Webhook mode (production)
        # python-telegram-bot's webhook server handles health checks on same port
        webhook_url = f"{WEBHOOK_URL}/webhook"
        logger.info(f"Starting in webhook mode: {webhook_url}")
        
        try:
            app.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path="webhook",
                webhook_url=webhook_url,
            )
        except Exception as e:
            logger.error(f"Webhook failed: {e}")
            sys.exit(1)
    else:
        # Polling mode (local dev / Railway without webhook)
        logger.info("Starting in polling mode...")
        try:
            app.run_polling(drop_pending_updates=True)
        except Exception as e:
            logger.error(f"Polling failed: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()