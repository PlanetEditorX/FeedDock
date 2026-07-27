FROM python:3.13-slim

ARG APP_VERSION=1.17.8

ENV APP_VERSION=${APP_VERSION} \
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
