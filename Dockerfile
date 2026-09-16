FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_HOST=0.0.0.0 APP_PORT=8000 APP_DATA_DIR=/app/.data APP_MODE=cloud
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
ARG INSTALL_HYBRID=true
RUN if [ "$INSTALL_HYBRID" = "true" ]; then pip install --no-cache-dir torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu; fi
RUN useradd --create-home --uid 10001 gridcast && mkdir -p /app/.data && chown gridcast:gridcast /app/.data
COPY backend/ ./backend/
COPY run.py ./
COPY --from=frontend /build/dist ./frontend/dist/
USER gridcast
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["python", "run.py"]
