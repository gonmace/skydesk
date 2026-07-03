# ── Stage 1: compilar CSS con Node (solo build, no va a producción) ─────────────
FROM node:22-slim AS css-builder

# Copiar todo el proyecto para que Tailwind escanee templates al compilar
COPY . /app/

WORKDIR /app/theme/static_src

# npm ci instala exactamente lo que dice package-lock.json (incluye devDependencies)
# Los módulos de Tailwind/DaisyUI solo existen en esta stage de build
RUN npm ci && npm run build

# ── Stage 2: imagen Python de producción (sin Node ni módulos npm) ─────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=core.settings

WORKDIR /app

# Sin gcc/libpq-dev: todas las dependencias (psycopg2-binary, pillow, PyMuPDF, uvloop…)
# instalan como wheels precompilados en py3.12 — no hay nada que compilar, y dejar
# toolchain en la imagen final solo agranda la superficie de ataque.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ./ ./

# CSS ya compilado y minificado desde la stage anterior
COPY --from=css-builder /app/static/css/dist/ ./static/css/dist/

# Usuario no-root (UID 1000 = usuario típico del VPS, así los volúmenes montados de
# ./staticfiles y ./media quedan con ownership compatible con el host).
RUN useradd --uid 1000 --create-home app && chown -R app:app /app
USER app

CMD ["sh", "entrypoint.sh"]
