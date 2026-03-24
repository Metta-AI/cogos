# Build context: project root (.)
# Usage: docker build -f dashboard/Dockerfile .

# Stage 1: Build Next.js frontend
FROM node:20-slim AS frontend
WORKDIR /build
COPY dashboard/frontend/package.json dashboard/frontend/package-lock.json ./
RUN npm ci
COPY dashboard/frontend/ ./
RUN npx next build

# Stage 2: Runtime
FROM python:3.12-slim
WORKDIR /app

# Install Node.js (to run standalone Next.js server)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Python package
COPY pyproject.toml README.md /app/
COPY src/ /app/src/
COPY images/ /app/images/
RUN pip install --no-cache-dir .

# Copy built frontend from stage 1
COPY --from=frontend /build/.next/standalone /app/frontend/
COPY --from=frontend /build/.next/static /app/frontend/.next/static

# Simple start script
COPY dashboard/start.sh /app/start.sh
RUN chmod +x /app/start.sh

RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=5174
ENV HOSTNAME=0.0.0.0

EXPOSE 5174 8100
ENTRYPOINT ["/app/start.sh"]
