# 🤖 Telegram Leecher Bot

A Telegram bot that downloads files from multiple sources and sends them back to you. Self-hosted Bot API support for unlimited file uploads (up to 2GB).

## ✨ Features

- 🔗 **Direct links** — Any download URL
- 🧲 **Magnet links** — BitTorrent magnets
- 📄 **Torrent files** — .torrent file URLs
- 📺 **YouTube / Aparat** — Video downloads
- 📁 **Google Drive** — GDrive file links
- 🚀 **Self-hosted Bot API** — Upload files up to 2GB (vs 50MB default)
- 🐳 **Docker** — One-command deployment
- 🌐 **Webhook + Polling** — Works everywhere

## 🚀 Quick Start

### 1. Create a Telegram Bot

1. Open [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the instructions
3. Copy the bot token

### 2. Run Locally (Polling Mode)

```bash
# Clone the repo
git clone https://github.com/TheLimoo/telegram-leecher.git
cd telegram-leecher

# Install dependencies
pip install -r requirements.txt

# Set your bot token
export BOT_TOKEN="your_token_here"

# Run!
python bot.py
```

### 3. Run with Docker

```bash
# Copy and edit env file
cp .env.example .env
# Edit .env with your BOT_TOKEN

# Run with docker-compose
docker-compose up -d
```

## 🌐 Deploy to Render

1. Fork this repo to your GitHub
2. Go to [render.com](https://render.com) → **New** → **Web Service**
3. Connect your GitHub repo
4. Render will auto-detect the Dockerfile
5. Add environment variables:
   - `BOT_TOKEN` — Your bot token
   - `WEBHOOK_URL` — Your Render URL (e.g., `https://your-app.onrender.com`)
   - `TELEGRAM_API_ID` — From [my.telegram.org](https://my.telegram.org) (optional)
   - `TELEGRAM_API_HASH` — From [my.telegram.org](https://my.telegram.org) (optional)
6. Deploy!

## 🚂 Deploy to Railway

1. Fork this repo to your GitHub
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
3. Select your repo
4. Railway auto-detects `railway.json`
5. **Add a persistent volume** (IMPORTANT):
   - Go to the **Volume** tab
   - Click **+ Add Volume**
   - Mount path: `/data`
   - Size: `500 MB` (or more)
6. Add environment variables in the **Variables** tab:
   - `BOT_TOKEN` — Your bot token
   - `TELEGRAM_API_ID` — From [my.telegram.org](https://my.telegram.org) (optional, for >50MB uploads)
   - `TELEGRAM_API_HASH` — From [my.telegram.org](https://my.telegram.org) (optional)
7. Deploy!

> ⚠️ **Volume is REQUIRED** for downloads! Without it, the bot can't save files. The volume size should be at least 500MB (default limit is 450MB per file).

## 🔓 Self-Hosted Bot API (Unlimited Uploads)

By default, Telegram Bot API limits file uploads to **50MB**. This bot supports a self-hosted Bot API server that removes this limit, allowing uploads up to **2GB**.

### How to Enable

1. Get API credentials from [my.telegram.org](https://my.telegram.org):
   - Go to **API Development Tools**
   - Create an application
   - Copy `api_id` and `api_hash`

2. Set environment variables:
   ```bash
   TELEGRAM_API_ID=12345678
   TELEGRAM_API_HASH=abcdef1234567890
   LOCAL_API_URL=http://127.0.0.1:8081
   ```

3. The bot automatically starts the self-hosted Bot API server on port 8081

### Without Self-Hosted API

If you don't set `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`, the bot falls back to the standard Telegram API with a **50MB** upload limit. This is fine for most use cases.

## 📋 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BOT_TOKEN` | ✅ | — | Telegram bot token from @BotFather |
| `ALLOWED_USERS` | ❌ | (empty = open) | Comma-separated Telegram user IDs |
| `WEBHOOK_URL` | ❌ | (polling) | Public URL for webhook mode |
| `PORT` | ❌ | `8443` | Webhook port |
| `LOCAL_API_URL` | ❌ | `http://127.0.0.1:8081` | Self-hosted Bot API URL |
| `TELEGRAM_API_ID` | ❌ | — | From my.telegram.org |
| `TELEGRAM_API_HASH` | ❌ | — | From my.telegram.org |
| `MAX_FILE_SIZE` | ❌ | `450MB` | Max download size (Railway volume: 500MB) |
| `DOWNLOAD_DIR` | ❌ | `/data/downloads` | **MUST be `/data` for Railway volume** |
| `DOWNLOAD_TIMEOUT` | ❌ | `300` | Download timeout (seconds) |
| `MAX_CONCURRENT` | ❌ | `3` | Max concurrent downloads |
| `AUTO_CLEANUP` | ❌ | `true` | Auto-delete files after sending |
| `POLLING_INTERVAL` | ❌ | `10` | Active polling interval (seconds) |
| `POLLING_IDLE_SLEEP` | ❌ | `30` | Idle polling interval (seconds) |

## 🤖 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | Detailed usage guide |
| `/cancel` | Cancel active download |

## 📡 Supported Sources

| Source | Detection | Tool |
|--------|-----------|------|
| Direct URL | Any `https://` link | aria2c |
| Magnet link | `magnet:?xt=urn:...` | aria2c (BitTorrent) |
| Torrent file | `*.torrent` URL | aria2c |
| YouTube | `youtube.com`, `youtu.be` | yt-dlp |
| Aparat | `aparat.com` | yt-dlp |
| Google Drive | `drive.google.com` | gdown |

## ⚠️ Limitations

- **Telegram Bot API**: 50MB max upload (2GB with self-hosted Bot API)
- **Free hosting**: Render/Railway free tiers have resource limits
- **Torrents**: May be slow on small instances; 5-minute timeout
- **YouTube**: Age-restricted videos may fail

## 🛠️ Tech Stack

- **Python 3.11** — Runtime
- **python-telegram-bot** — Telegram Bot API wrapper
- **aria2c** — Download accelerator (direct + torrents)
- **yt-dlp** — YouTube/Aparat video downloader
- **gdown** — Google Drive downloader
- **Docker** — Containerization
- **Self-hosted Bot API** — Telegram's official Bot API server (C++)

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch
3. Commit your changes
4. Push and open a PR

---

Made with ❤️ by [TheLimoo](https://github.com/TheLimoo)
