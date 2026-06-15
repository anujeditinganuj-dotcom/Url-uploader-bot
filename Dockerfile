FROM python:3.11-slim

# System dependencies (yt-dlp + ffmpeg required)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    gcc \
    g++ \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project
COPY . /app/

# Upgrade pip + install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -U yt-dlp

# Environment safety (fix SSL / fetch issues)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Optional port (safe for web bots)
EXPOSE 5000

# Run bot
CMD ["python3", "-m", "bot"]
