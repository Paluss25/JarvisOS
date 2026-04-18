FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nodejs \
    npm \
    openssh-client \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Claude CLI
RUN npm install -g @anthropic-ai/claude-code

# Source code
COPY src/ ./src/
COPY agents.yaml .
COPY supervisord.conf /etc/supervisor/supervisord.conf
COPY scripts/ ./scripts/

# Generate supervisord program configs from agents.yaml
RUN python scripts/gen_supervisord.py

# Workspace + shared memory bind-mounted at runtime
# /app/workspace/jarvis, /app/workspace/roger, /app/shared

EXPOSE 8000 8900

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health && curl -f http://localhost:8900/health || exit 1

RUN chmod +x scripts/entrypoint.sh

CMD ["scripts/entrypoint.sh"]
