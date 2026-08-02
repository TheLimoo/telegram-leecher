#!/usr/bin/env python3
"""Telegram Leecher Bot — main entry point.

Supports:
- Polling mode (local dev)
- Webhook mode (production on Render/Railway)
- Self-hosted Bot API (removes 50MB upload limit)
- Health check endpoint for Railway/Render
"""
import logging
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from config import BOT_TOKEN, WEBHOOK_URL, PORT, LOCAL_API_URL, DOWNLOAD_DIR
from handlers import start_cmd, help_cmd, cancel_cmd, handle_message, post_init

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    """Simple health check handler for Railway/Render."""
    
    def do_GET(self):
        if self.path in ("/", "/health", "/healthz", "/ready"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_HEAD(self):
        self.do_GET()
    
    def log_message(self, format, *args):
        logger.info(f"Health check: {self.path} -> 200")


def start_health_server():
    """Start health check server in background thread."""
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health check server started on port {PORT}")


def main() -> None:
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set! Set it in environment or .env file.")
        sys.exit(1)

    # Ensure download directory exists
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # Start health check server (needed for Railway/Render)
    start_health_server()

    # Build application
    # If LOCAL_API_URL is set, connect to self-hosted Bot API server
    builder = ApplicationBuilder().token(BOT_TOKEN)
    
    if LOCAL_API_URL:
        builder = builder.base_url(LOCAL_API_URL)
        builder = builder.base_file_url(LOCAL_API_URL)
        logger.info(f"Using self-hosted Bot API: {LOCAL_API_URL}")
    else:
        logger.info("Using standard api.telegram.org (50MB limit)")

    app = builder.build()

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
        webhook_url = f"{WEBHOOK_URL}/webhook"
        logger.info(f"Starting in webhook mode: {webhook_url}")
        
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path="webhook",
            webhook_url=webhook_url,
        )
    else:
        # Polling mode (local dev)
        logger.info("Starting in polling mode...")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
