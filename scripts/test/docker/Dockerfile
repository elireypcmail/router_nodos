# API del nodo (FastAPI) para stacks de prueba en scripts/test/docker-compose.nodos.yml
# MySQL 5.6 va en un servicio aparte (misma red interna por tienda).
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        default-libmysqlclient-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x scripts/test/docker/entrypoint-api.sh \
    && chmod +x scripts/test/docker/write-app-dotenv.sh \
    && chmod +x scripts/test/docker/wait-erp-schema.sh \
    && apt-get update \
    && apt-get install -y --no-install-recommends default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    NODO_HOST=0.0.0.0 \
    NODO_PORT=8443 \
    NODO_ALLOW_INSECURE=true \
    NODO_DEV_RELOAD=false \
    SYNC_DB_PATH=/app/data/sync.sqlite \
    HUEY_DB_PATH=/app/data/huey.sqlite

RUN mkdir -p /app/data

EXPOSE 8443

ENTRYPOINT ["/app/scripts/test/docker/entrypoint-api.sh"]
