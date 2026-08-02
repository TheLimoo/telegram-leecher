FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    aria2 \
    ffmpeg \
    cmake \
    g++ \
    git \
    libssl-dev \
    zlib1g-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Build self-hosted Telegram Bot API server
# This removes the 50MB upload limit (allows up to 2GB)
RUN git clone --depth 1 https://github.com/telegram-bot-api/telegram-bot-api.git /tmp/botapi \
    && cd /tmp/botapi \
    && cmake -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build -j$(nproc) \
    && cp build/telegram-bot-api /usr/local/bin/ \
    && rm -rf /tmp/botapi

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .
RUN chmod +x start_bot_api.sh

# Bot API server on 8081, bot webhook on $PORT
EXPOSE 8081

# Create download directory
RUN mkdir -p /tmp/downloads

CMD ["./start_bot_api.sh"]
