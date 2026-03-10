# Build context: project root (.)
# Usage: docker build -f src/cogos/io/discord/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

CMD ["python", "-m", "cogos.io.discord.bridge"]
