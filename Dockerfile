# ==============================================================================
# Stage 1: Build Frontend Assets (Vite + React PWA)
# ==============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy frontend dependency manifests
COPY frontend/package.json frontend/package-lock.json* frontend/pnpm-lock.yaml* ./

# Install frontend dependencies
RUN if [ -f pnpm-lock.yaml ]; then \
      npm install -g pnpm && pnpm install --frozen-lockfile; \
    elif [ -f package-lock.json ]; then \
      npm ci; \
    else \
      npm install; \
    fi

# Copy frontend source code and configuration
COPY frontend/ ./

# Compile production SPA bundle into dist/
RUN npm run build

# ==============================================================================
# Stage 2: Production Python Runtime (FastAPI Backend + Integrated SPA)
# ==============================================================================
FROM python:3.11-slim AS runtime

# Set environment variables for production execution
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=prod \
    FRONTEND_DIST=/app/frontend/dist \
    LIFEASSISTANT_DB_PATH=/app/data/liftassistant.db \
    LIFEASSISTANT_CAS_ROOT=/app/data/receipt_store \
    PORT=8000

WORKDIR /app

# Install lightweight system dependencies (curl for container healthcheck, sqlite3)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code, prompts, and default configurations
COPY liftassistant/ ./liftassistant/
COPY prompts/ ./prompts/
COPY credentials.json* token.json* ./

# Copy compiled frontend from Stage 1 into the runtime image
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Ensure persistent data directory exists
RUN mkdir -p /app/data/receipt_store

# Expose HTTP port for API and frontend UI
EXPOSE 8000

# Docker healthcheck querying the /api/v1/health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://127.0.0.1:8000/api/v1/health || exit 1

# Start Uvicorn ASGI server
CMD ["uvicorn", "liftassistant.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
