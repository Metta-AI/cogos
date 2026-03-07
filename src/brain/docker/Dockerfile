FROM python:3.12-slim

# System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux vim curl wget sudo git unzip \
    && rm -rf /var/lib/apt/lists/*

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*

# Node.js 22 (runtime for Claude Code)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (official installer)
RUN curl -fsSL https://cli.claude.ai/install.sh | sh

# uv (Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# AWS CLI v2
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install && rm -rf /tmp/aws /tmp/awscliv2.zip

# SSM agent (required for ECS Exec)
RUN curl -fsSL "https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/debian_$(dpkg --print-architecture)/amazon-ssm-agent.deb" \
    -o /tmp/ssm.deb && dpkg -i /tmp/ssm.deb && rm /tmp/ssm.deb

# Project source
COPY src/ /app/src/
COPY pyproject.toml /app/
COPY eggs/ /app/eggs/
WORKDIR /app

# Install project in the system Python (so cogent/mind CLIs are available)
RUN uv pip install --system -e .

# Entrypoint
COPY src/brain/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
