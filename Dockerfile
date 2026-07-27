FROM python:3.12.10-slim-bookworm AS builder

WORKDIR /build
COPY pyproject.toml README.md /build/
COPY src /build/src
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels ".[finance,ui]"

FROM python:3.12.10-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN groupadd --system --gid 10001 deepresearch \
    && useradd --system --uid 10001 --gid deepresearch --home-dir /app deepresearch

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels "deepresearch-agent[finance,ui]" \
    && rm -rf /wheels

COPY src /app/src
COPY ui /app/ui
COPY data /app/data
COPY prompts /app/prompts
RUN mkdir -p /app/data/runtime \
    && chown -R deepresearch:deepresearch /app

USER deepresearch
EXPOSE 8000 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]

CMD ["uvicorn", "deepresearch_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
