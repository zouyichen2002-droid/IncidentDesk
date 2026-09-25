FROM python:3.12.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /usr/local/bin/uv
WORKDIR /app
COPY worker/pyproject.toml worker/uv.lock ./
RUN uv sync --frozen --no-dev
COPY demo/server.py demo/log_store.py ./
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn","server:app","--host","0.0.0.0","--port","8090"]
