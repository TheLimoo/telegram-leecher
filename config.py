"""Configuration from environment variables."""
import os

# Telegram Bot Token (required)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Comma-separated Telegram user IDs (optional, empty = open to all)
ALLOWED_USERS = [
    int(uid.strip())
    for uid in os.environ.get("ALLOWED_USERS", "").split(",")
    if uid.strip().isdigit()
]

# Max download size in bytes (default: 2GB)
MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", 2 * 1024 * 1024 * 1024))

# Temp download directory
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/tmp/downloads")

# Webhook config (empty = polling mode)
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
PORT = int(os.environ.get("PORT", 8443))

# Self-hosted Bot API (removes 50MB limit)
LOCAL_API_URL = os.environ.get("LOCAL_API_URL", "http://127.0.0.1:8081")

# Telegram API credentials for self-hosted Bot API server
TELEGRAM_API_ID = os.environ.get("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "")

# Download timeout in seconds
DOWNLOAD_TIMEOUT = int(os.environ.get("DOWNLOAD_TIMEOUT", 300))

# Max concurrent downloads
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", 3))

# Clean up files after sending
AUTO_CLEANUP = os.environ.get("AUTO_CLEANUP", "true").lower() == "true"
