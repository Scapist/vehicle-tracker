# syntax=docker/dockerfile:1
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY backend/ ./
COPY --from=web /web/dist /static
ENV STATIC_DIR=/static DATA_DIR=/data PATH="/app/.venv/bin:$PATH"
VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
