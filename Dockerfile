# syntax=docker/dockerfile:1

FROM python:3.11-slim-bookworm AS runtime

ARG INSTALL_EXTRAS=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    AGENT_PROVIDER=mock \
    AGENT_PLANNER=rule

WORKDIR /app

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY --chown=app:app pyproject.toml README.md ./
COPY --chown=app:app src ./src

RUN python -m pip install ".${INSTALL_EXTRAS}" \
    && mkdir -p /app/.cache \
    && chown -R app:app /app

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["python", "-m", "uvicorn", "travel_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
