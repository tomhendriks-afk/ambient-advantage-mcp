FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# requirements.txt copied first so changes to app/ don't bust the
# pip-install layer cache.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app

# Drop root: defense in depth. The MCP server is read-only and makes no
# filesystem writes, so a non-privileged user is sufficient. Port 8080
# doesn't need root (it's > 1024).
RUN useradd --create-home --shell /bin/false appuser \
    && chown -R appuser:appuser /srv
USER appuser

# Cloud Run injects $PORT (default 8080). uvicorn binds to it.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75"]
