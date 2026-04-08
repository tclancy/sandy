# Sandy — text command router daemon
# Build: docker build -t ghcr.io/tclancy/sandy .
# Run:   docker run --env-file .env -v /path/to/sandy.toml:/home/sandy/.config/sandy/sandy.toml ghcr.io/tclancy/sandy

FROM python:3.14-slim

# Install system deps for pychromecast (zeroconf), adb, and network printing
RUN apt-get update && apt-get install -y --no-install-recommends \
    adb \
    cups-client \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root user
RUN useradd -m -u 1000 sandy
WORKDIR /app
RUN chown sandy:sandy /app

USER sandy

# Copy project files
COPY --chown=sandy:sandy pyproject.toml uv.lock ./
COPY --chown=sandy:sandy sandy/ ./sandy/

# Install dependencies (no dev deps, compile bytecode)
RUN uv sync --no-dev --compile-bytecode --frozen

# Config is mounted at runtime:
#   -v /path/to/sandy.toml:/home/sandy/.config/sandy/sandy.toml:ro
# All secret env vars can also be passed via --env-file or environment:
#   SLACK_APP_TOKEN, SLACK_BOT_TOKEN, HARDCOVER_API_KEY, etc.

ENTRYPOINT ["uv", "run", "sandy", "serve"]
