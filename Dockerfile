FROM python:3.13-slim

ARG APP_VERSION=dev
ARG APP_REVISION=unknown
ARG APP_CREATED_AT=unknown

LABEL org.opencontainers.image.title="FeedDock" \
      org.opencontainers.image.description="Self-hosted RSS automation service for qBittorrent" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${APP_REVISION}" \
      org.opencontainers.image.created="${APP_CREATED_AT}"

ENV APP_VERSION=${APP_VERSION} \
    APP_REVISION=${APP_REVISION} \
    APP_CREATED_AT=${APP_CREATED_AT} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docker-entrypoint.py /usr/local/bin/feeddock-entrypoint
RUN mkdir -p /data /media \
    && chown -R 0:0 /app /data /media \
    && chmod +x /usr/local/bin/feeddock-entrypoint

EXPOSE 8000
VOLUME ["/data", "/media"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

ENTRYPOINT ["/usr/local/bin/feeddock-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
