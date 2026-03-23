# ── Stage 1: compilar CSS con Node ────────────────────────────────────────────
FROM node:22-slim AS css-builder

# Copiar todo el proyecto para que Tailwind pueda escanear los templates
COPY . /app/

WORKDIR /app/theme/static_src
RUN npm install
RUN npm run build

# ── Stage 2: imagen Python de producción ──────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=core.settings

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ./ ./

# Copiar el CSS compilado desde el stage anterior
COPY --from=css-builder /app/static/css/dist/ ./static/css/dist/

CMD ["sh", "entrypoint.sh"]
