# builder で作った .venv を runner にそのまま COPY するので、両 stage の Python を同じ版にする
ARG PYTHON_VERSION=3.14

FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

FROM python:${PYTHON_VERSION}-slim-bookworm AS runner

LABEL org.opencontainers.image.source="https://github.com/msageha/daikin-air-purifier-MCK706A-W" \
      org.opencontainers.image.licenses="MIT"

RUN useradd --create-home --uid 10001 appuser

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src /app/src

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

USER 10001
EXPOSE 8000

# DAIKIN_HOST (必須) はイメージに含めず、実行時に環境変数で渡す。
# 本体への通信の直列化と読み取りの共有はプロセスの中でしか効かないので、
# uvicorn が WEB_CONCURRENCY から worker を増やさないよう 1 に固定する。
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
