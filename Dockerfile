FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

COPY requirements-prod.txt .
RUN pip install --no-cache-dir --requirement requirements-prod.txt \
    && addgroup --system app \
    && adduser --system --ingroup app app

COPY --chown=app:app app ./app

USER app

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
