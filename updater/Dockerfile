FROM docker:27-cli

RUN apk add --no-cache python3

WORKDIR /opt/feeddock-updater
COPY updater.py ./updater.py

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UPDATER_BIND=0.0.0.0 \
    UPDATER_PORT=8090

EXPOSE 8090

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=2)"

CMD ["python3", "/opt/feeddock-updater/updater.py"]
