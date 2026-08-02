#!/bin/bash
set -e

# Start self-hosted Bot API server if credentials are provided
if [ -n "$TELEGRAM_API_ID" ] && [ -n "$TELEGRAM_API_HASH" ]; then
    echo "🔧 Starting self-hosted Bot API server..."
    mkdir -p /tmp/botapi-data
    
    telegram-bot-api \
        --api_id="$TELEGRAM_API_ID" \
        --api_hash="$TELEGRAM_API_HASH" \
        --http_port=8081 \
        --dir=/tmp/botapi-data \
        --local &
    
    BOTAPI_PID=$!
    echo "⏳ Waiting for Bot API server to start..."
    
    # Wait for the server to be ready (max 30 seconds)
    for i in $(seq 1 30); do
        if curl -s http://127.0.0.1:8081/ > /dev/null 2>&1; then
            echo "✅ Bot API server ready on :8081 (unlimited uploads!)"
            break
        fi
        if [ $i -eq 30 ]; then
            echo "⚠️ Bot API server failed to start, falling back to standard API"
            unset LOCAL_API_URL
        fi
        sleep 1
    done
else
    echo "ℹ️ No TELEGRAM_API_ID/HASH — using standard api.telegram.org (50MB limit)"
    echo "   Set these env vars to enable unlimited uploads!"
fi

# Start the bot
echo "🤖 Starting Leecher Bot..."
exec python bot.py
