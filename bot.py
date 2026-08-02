#!/usr/bin/env python3
"""Telegram Leecher Bot — main entry point.

Supports:
- Polling mode (local dev / Railway) with idle optimization
- Self-hosted Bot API (removes 50MB upload limit)
- Health check endpoint for Railway/Render (separate thread)
- Adaptive polling: reduces API calls when idle
"""
import logging
import os
import sys
import threading
import time
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from config import (
    BOT_TOKEN, WEBHOOK_URL, PORT, LOCAL_API_URL, DOWNLOAD_DIR,
    POLLING_INTERVAL, POLLING_TIMEOUT, POLLING_IDLE_SLEEP, KEEP_ALIVE_INTERVAL
)
from handlers import start_cmd, help_cmd, cancel_cmd, handle_message, post_init, test_api_cmd, quality_cmd

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Track last activity time for idle detection
_last_activity = time.time()
_activity_lock = threading.Lock()


class HealthHandler(BaseHTTPRequestHandler):
    """Simple health check handler for Railway/Render."""
    
    def do_GET(self):
        if self.path in ("/", "/health", "/healthz", "/ready"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","mode":"polling-idle-optimized"}')
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_HEAD(self):
        self.do_GET()
    
    def log_message(self, format, *args):
        # Suppress logging for health checks
        pass


def start_health_server():
    """Start health check server in background thread on PORT."""
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health check server started on port {PORT}")


def record_activity():
    """Record when bot receives activity."""
    global _last_activity
    with _activity_lock:
        _last_activity = time.time()


def get_idle_time() -> float:
    """Get seconds since last activity."""
    with _activity_lock:
        return time.time() - _last_activity


async def adaptive_polling_loop(app) -> None:
    """
    Adaptive polling loop that reduces API calls during idle periods.
    
    - Active mode: poll every POLLING_INTERVAL (30s)
    - Idle mode: poll every POLLING_IDLE_SLEEP (60s)
    - After 5 min idle: switch to keep-alive mode (only health checks)
    """
    logger.info(f"Polling config: interval={POLLING_INTERVAL}s, idle_sleep={POLLING_IDLE_SLEEP}s")
    
    while True:
        idle_time = get_idle_time()
        
        # If completely idle (>5 min), only do keep-alive health checks
        if idle_time > KEEP_ALIVE_INTERVAL:
            logger.debug(f"Keep-alive mode: idle for {idle_time:.0f}s, sleeping {KEEP_ALIVE_INTERVAL}s")
            await asyncio.sleep(KEEP_ALIVE_INTERVAL)
            continue
        
        # If idle (>1 min), reduce polling frequency
        if idle_time > 60:
            sleep_time = POLLING_IDLE_SLEEP
            logger.debug(f"Idle mode: idle for {idle_time:.0f}s, polling every {sleep_time}s")
        else:
            sleep_time = POLLING_INTERVAL
            logger.debug(f"Active mode: polling every {sleep_time}s")
        
        # Do one polling iteration
        try:
            # Get updates with long timeout to reduce CPU usage
            updates = await app.bot.get_updates(
                offset=app.update_queue.maxsize,  # Only get new updates
                timeout=POLLING_TIMEOUT,
                allowed_updates=None,
            )
            
            if updates:
                record_activity()  # Record activity on updates
                for update in updates:
                    await app.process_update(update)
        
        except Exception as e:
            logger.error(f"Polling error: {e}")
        
        await asyncio.sleep(sleep_time)


def main() -> None:
    logger.info("=== Telegram Leecher Bot Starting ===")
    logger.info(f"PORT: {PORT}")
    logger.info(f"WEBHOOK_URL: {WEBHOOK_URL or 'not set (polling mode)'}")
    logger.info(f"LOCAL_API_URL: {LOCAL_API_URL or 'not set (standard API)'}")
    logger.info(f"DOWNLOAD_DIR: {DOWNLOAD_DIR}")
    logger.info(f"Idle optimization: POLLING_INTERVAL={POLLING_INTERVAL}s, IDLE_SLEEP={POLLING_IDLE_SLEEP}s")
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set! Set it in environment or .env file.")
        sys.exit(1)

    # Ensure download directory exists
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # Start health check server (required for Railway/Render)
    start_health_server()

    # Build application
    if LOCAL_API_URL:
        api_base = LOCAL_API_URL.rstrip('/')
        base_url = f"{api_base}/bot"
        base_file_url = f"{api_base}/file/bot"
        logger.info(f"Using self-hosted Bot API: {base_url}")
        builder = ApplicationBuilder().token(BOT_TOKEN).base_url(base_url).base_file_url(base_file_url)
    else:
        logger.info("Using standard api.telegram.org (50MB limit)")
        builder = ApplicationBuilder().token(BOT_TOKEN)

    # Increase timeouts for large file uploads
    builder = builder.read_timeout(600).write_timeout(600).connect_timeout(30).pool_timeout(30)

    try:
        app = builder.build()
    except Exception as e:
        logger.error(f"Failed to build application: {e}")
        sys.exit(1)

    # Register handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("quality", quality_cmd))
    app.add_handler(CommandHandler("testapi", test_api_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Post-init: set bot commands
    app.post_init = post_init

    # Add error handler
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error(f"Exception: {context.error}")
        if "Conflict" in str(context.error):
            logger.warning("Another bot instance detected - waiting for it to terminate...")
        elif "RetryAfter" in str(type(context.error)) or "Flood control" in str(context.error):
            logger.warning("Flood control in handler, backing off...")
            await asyncio.sleep(5)
    
    app.add_error_handler(error_handler)

    # Start the bot in optimized polling mode
    logger.info("Starting in adaptive polling mode (idle-optimized)...")
    import time
    time.sleep(10)  # Longer delay to avoid flood control on rapid restarts
    
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Use polling with idle optimization
            app.run_polling(
                drop_pending_updates=True,
                poll_interval=POLLING_INTERVAL,
                timeout=POLLING_TIMEOUT,
                close_loop=False,
            )
            break  # Success, exit loop
        except Exception as e:
            logger.error(f"Polling failed (attempt {retry_count + 1}/{max_retries}): {e}")
            retry_count += 1
            
            # Don't retry on InvalidToken - token is wrong
            if "InvalidToken" in str(type(e)) or "Unauthorized" in str(e):
                logger.error("Invalid token - check BOT_TOKEN environment variable")
                sys.exit(1)
            
            # Handle RetryAfter with proper wait time
            if "RetryAfter" in str(type(e)) or "Flood control" in str(e):
                # Extract retry_after from exception
                import re
                retry_after_match = re.search(r'Retry in (\d+) seconds', str(e))
                if retry_after_match:
                    wait_time = int(retry_after_match.group(1)) + 5  # Add buffer
                    logger.warning(f"Flood control - waiting {wait_time}s (from Telegram)...")
                    time.sleep(wait_time)
                else:
                    # Fallback: exponential backoff
                    wait_time = 30 * retry_count
                    logger.warning(f"Flood control - waiting {wait_time}s...")
                    time.sleep(wait_time)
            else:
                # Retry on other network errors
                if retry_count < max_retries:
                    wait_time = 10 * retry_count
                    logger.warning(f"Retrying in {wait_time}s...")
                    time.sleep(wait_time)
            
            if retry_count >= max_retries:
                logger.error("Max retries reached, exiting")
                sys.exit(1)


if __name__ == "__main__":
    main()