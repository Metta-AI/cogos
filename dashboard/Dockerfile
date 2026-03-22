# Build context: project root (.)
# Usage: docker build -f dashboard/Dockerfile .
#
# The frontend is NOT baked into the image. On startup the entrypoint
# downloads a pre-built Next.js bundle from S3 (set DASHBOARD_ASSETS_S3).
# This lets us redeploy frontend changes in seconds without rebuilding
# the Docker image.

FROM python:3.12-slim
WORKDIR /app

# Install Node.js (needed to run standalone Next.js server) + AWS CLI (for S3 sync)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unzip \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscli.zip \
    && unzip -q /tmp/awscli.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/aws /tmp/awscli.zip /var/lib/apt/lists/*

# Install the cogent package (provides dashboard backend + all deps)
COPY pyproject.toml README.md /app/
COPY src/ /app/src/
COPY images/ /app/images/
RUN pip install --no-cache-dir .

# Copy entrypoint
COPY dashboard/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Bake the version into the image for auto-rebuild detection
COPY dashboard/DOCKER_VERSION /app/DOCKER_VERSION

RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=5174
ENV HOSTNAME=0.0.0.0

EXPOSE 5174 8100
ENTRYPOINT ["/app/entrypoint.sh"]
