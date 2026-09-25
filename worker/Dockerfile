FROM python:3.12.13-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /usr/local/bin/uv
WORKDIR /app
COPY worker/pyproject.toml worker/uv.lock ./
RUN uv sync --frozen --no-dev
COPY worker/incident_worker ./incident_worker
COPY --chmod=755 worker/entrypoint.sh /app/entrypoint.sh
RUN useradd -u 10001 -m worker
USER worker
ARG CODE_VERSION=working-tree
ENV CODE_VERSION=$CODE_VERSION
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python","-m","incident_worker.main"]
