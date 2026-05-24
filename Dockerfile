FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY ui /app/ui
COPY data /app/data
COPY prompts /app/prompts

RUN pip install --no-cache-dir -e .

EXPOSE 8000 8501

