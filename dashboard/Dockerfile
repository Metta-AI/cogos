# Build context: project root (.)
# Usage: docker build -f dashboard/Dockerfile .

# Stage 1: Build Next.js frontend
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY dashboard/frontend/package.json dashboard/frontend/package-lock.json ./
RUN npm ci
COPY dashboard/frontend/ .
RUN mkdir -p public
RUN npm run build

# Stage 2: Python runtime with both backend and frontend
FROM python:3.12-slim
WORKDIR /app

# Install Node.js (needed to run standalone Next.js server)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install the cogent package (provides dashboard backend + all deps)
COPY pyproject.toml /app/pyproject.toml
COPY src/ /app/src/
RUN pip install --no-cache-dir .

# Copy standalone Next.js output
COPY --from=frontend-build /build/.next/standalone /app/frontend
COPY --from=frontend-build /build/.next/static /app/frontend/.next/static
COPY --from=frontend-build /build/public /app/frontend/public

# Copy entrypoint
COPY dashboard/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PORT=5174
ENV HOSTNAME=0.0.0.0

EXPOSE 5174 8100
ENTRYPOINT ["/app/entrypoint.sh"]
