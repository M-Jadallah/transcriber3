# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim-bookworm AS python-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       gcc \
       g++ \
       git \
       libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Build context is the repository root. Copy the dependency manifests first so
# Docker can cache package installation independently from application changes.
COPY backend/requirements.txt /tmp/requirements.txt
COPY backend/requirements-formatting.txt /tmp/requirements-formatting.txt

RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
    && if [ -s /tmp/requirements-formatting.txt ]; then \
         /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements-formatting.txt; \
       fi \
    && /opt/venv/bin/pip check

FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:$PATH \
    HOME=/home/app \
    TZ=Asia/Amman

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       curl \
       ffmpeg \
       libpq5 \
       nodejs \
       tini \
       tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/app app

WORKDIR /app

COPY --from=python-builder /opt/venv /opt/venv
COPY --chown=10001:10001 backend/ /app/

RUN test -f /app/app/main.py \
    && test -f /app/alembic.ini \
    && mkdir -p /data/audio /data/exports /data/youtube /data/formatting \
    && chown -R 10001:10001 /app /data /home/app

USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
