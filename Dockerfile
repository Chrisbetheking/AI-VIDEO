FROM node:22-bookworm AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DATA_DIR=/app/data \
    STATIC_DIR=/app/static
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-noto-cjk fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY backend/app /app/app
COPY --from=frontend-build /frontend/dist /app/static
RUN mkdir -p /app/data/uploads /app/data/outputs /app/data/tmp
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
