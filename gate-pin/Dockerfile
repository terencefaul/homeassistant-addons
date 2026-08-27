# Declared before any FROM so it is in global scope and both stages can see it.
# An ARG after a FROM is scoped to that stage only.
ARG BUILD_FROM

# ---- frontend build -------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- add-on ---------------------------------------------------------------
FROM $BUILD_FROM

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

RUN apk add --no-cache nginx netcat-openbsd

COPY requirements.txt /tmp/requirements.txt
# --only-binary=:all: is deliberate. pydantic-core is Rust; if a musl wheel is
# ever missing for an architecture the build must fail loudly here rather than
# silently compiling Rust and turning a two-minute build into twenty.
RUN pip install --no-cache-dir --only-binary=:all: -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/http.d/ /etc/nginx/http.d/
COPY rootfs/app/ /app/
COPY --from=frontend /build/dist/guest /app/www/guest
COPY --from=frontend /build/dist/admin /app/www/admin
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /app
CMD ["/run.sh"]
