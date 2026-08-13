# Backend-only image for local/debug. Production uses the repo-root Dockerfile.
FROM python:3.11-slim

WORKDIR /app

# curl is used by the Docker healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install the project with its dependencies (single source of truth: pyproject.toml)
COPY pyproject.toml .
COPY sonicverse/ ./sonicverse/
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip \
    && pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple .

# Create runtime directories (covers/logs under /data; music at /music).
# SQLite's data/database/ directory is created at startup when using default sqlite.
RUN mkdir -p /data/covers /data/logs /music

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "sonicverse.main:app", "--host", "0.0.0.0", "--port", "8000"]
