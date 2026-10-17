FROM python:3.11-slim
# PLAT-1302: install from the locked uv project (pyproject.toml + uv.lock) — the
# single source of truth. The build pins exact, verifiable resolved versions via
# `uv sync --locked`, so OSV/Trivy scan the actually-deployed versions instead of
# resolving the old open `>=` ranges to the range floor (the false-positive CVE
# flood). uv is pinned to the same 0.11.26 used to generate the lock.
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /bin/

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PYTHON_DOWNLOADS=0
ENV UV_LINK_MODE=copy

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    netcat-openbsd \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Create log directories
RUN mkdir -p /var/log/supervisor /var/log/django

# Install Python dependencies from the lockfile first (cached layer independent of code).
COPY pyproject.toml uv.lock /app/
RUN uv sync --locked --no-dev --no-install-project

# Copy project
COPY . .

# Put the synced project venv on PATH so `gunicorn`, `python manage.py`, and the
# supervisor-managed MCP server resolve the locked dependencies.
ENV PATH="/app/.venv/bin:$PATH"

# Copy supervisord config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose port
EXPOSE 8003 18103

# Run supervisord
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]

# PLAT-10781: rebuild-trigger after 3.11-slim base cascade (ruling: in-scope; no behavioral change).
