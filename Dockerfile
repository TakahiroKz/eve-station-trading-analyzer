# Imagen única: sirve la API (FastAPI) y el build estático de la PWA desde el mismo
# proceso (ver el mount condicional al final de backend/api/main.py) — mismo origen,
# sin CORS que configurar en producción. La MISMA imagen también corre los dos
# motores programados (scheduler/run.py, scheduler/orders_run.py), invocados como
# contenedores de un solo uso por cron del host — ver docker-compose.yml.
#
# Build de dos etapas: el frontend (Node) se compila en una etapa aparte y solo se
# copia el resultado (dist/) a la imagen final de Python — así la imagen que corre
# en producción no carga con Node ni node_modules.

# Imágenes base fijadas por digest (reproducible y a salvo de un cambio de etiqueta). Para
# actualizarlas: docker pull <imagen> y copiar el nuevo digest (docker inspect --format "{{index .RepoDigests 0}}").
# El frontend compilado (HTML/JS/CSS) no depende de la arquitectura: se construye una sola vez en la
# plataforma del runner y se copia a la imagen amd64 y a la arm64 (en emulación QEMU tardaba más de una hora).
FROM --platform=$BUILDPLATFORM node:22-alpine@sha256:0e1754758c2df4cfa3e68d59e2e1b7374bb7fd9ea6328eaaacf15cc934af8202 AS frontend-builder
WORKDIR /build/frontend/app
COPY frontend/app/package.json frontend/app/package-lock.json ./
RUN npm ci
COPY frontend/app/ ./
RUN npm run build

FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535 AS final
WORKDIR /app

# Parches de seguridad del sistema operativo publicados después de la imagen base.
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Sin .pyc ni buffer de salida: el contenedor corre con el sistema de archivos de solo lectura.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y setuptools wheel

COPY analytics/ ./analytics/
COPY backend/ ./backend/
COPY ingestion/ ./ingestion/
COPY notifications/ ./notifications/
COPY reporting/ ./reporting/
COPY scheduler/ ./scheduler/
COPY storage/ ./storage/

COPY --from=frontend-builder /build/frontend/app/dist ./frontend/app/dist

EXPOSE 8001
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8001"]
