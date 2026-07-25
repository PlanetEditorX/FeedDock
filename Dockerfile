FROM python:3.12-slim

ARG APP_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION} \
    DATA_DIR=/data \
    DATABASE_PATH=/data/feeddock.db

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY docker-entrypoint.py ./docker-entrypoint.py
COPY VERSION ./VERSION
RUN chmod +x /app/docker-entrypoint.py

EXPOSE 8000
VOLUME ["/data"]
ENTRYPOINT ["python", "/app/docker-entrypoint.py"]
