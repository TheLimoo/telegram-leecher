FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    aria2 \
    ffmpeg \
    curl \
    build-essential \
    cmake \
    libssl-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Build self-hosted Telegram Bot API server (removes 50MB upload limit)
# Download both bot-api and its tdlib dependency as tarballs (no git needed)
RUN mkdir -p /tmp/botapi-build/td \
    && curl -sL https://github.com/tdlib/telegram-bot-api/archive/refs/heads/master.tar.gz \
       | tar xz --strip-components=1 -C /tmp/botapi-build \
    && curl -sL https://github.com/tdlib/td/archive/refs/heads/master.tar.gz \
       | tar xz --strip-components=1 -C /tmp/botapi-build/td \
    && cd /tmp/botapi-build \
    && cmake -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build -j$(nproc) \
    && cp build/telegram-bot-api /usr/local/bin/ \
    && rm -rf /tmp/botapi-build \
    && apt-get purge -y --auto-remove build-essential cmake libssl-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .
RUN chmod +x start_bot_api.sh

# Create download directory
RUN mkdir -p /tmp/downloads

CMD ["./start_bot_api.sh"]
