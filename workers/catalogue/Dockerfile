FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

# Installer uv (même outil que les autres workers du projet)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml .
COPY pricetracker_catalogue/ ./pricetracker_catalogue/
COPY prompts/ ./prompts/

RUN uv pip install --system .

ENTRYPOINT ["python", "-m", "pricetracker_catalogue.main"]
