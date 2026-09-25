FROM python:3.14.6-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /usr/local/bin/uv
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY conf ./conf
COPY prompts ./prompts
COPY main.py ./main.py
ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --uid 10001 --create-home agent && chown -R agent:agent /app
USER agent
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8092"]
