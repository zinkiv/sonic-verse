# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gosu \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
COPY backend/sonicverse/ ./sonicverse/
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip \
    && pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple .

COPY --from=frontend-builder /app/frontend/dist /app/web
COPY docker/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

# Only user-facing knobs here (NAS / Container Manager will list these).
# Paths are fixed inside entrypoint, not exposed as image ENV.
ENV SERVER_PORT=7526 \
    DATABASE_TYPE= \
    DATABASE_URL= \
    PYTHONUNBUFFERED=1

RUN mkdir -p /app/logs /data/transfer /data/database /data/covers /data/library

EXPOSE 7526

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${SERVER_PORT:-7526}/health" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
