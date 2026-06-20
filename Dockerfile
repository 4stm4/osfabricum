FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc make bc flex bison \
    libssl-dev libelf-dev libncurses-dev \
    xz-utils bzip2 \
    && rm -rf /var/lib/apt/lists/*

COPY vendor/ vendor/
RUN pip install --no-cache-dir vendor/*.whl

COPY . .
RUN pip install --no-cache-dir ".[dev]"

RUN mkdir -p /data /etc/osfabricum && \
    printf '[database]\nurl = "sqlite+aiosqlite:////data/osfabricum.db"\n' \
    > /etc/osfabricum/osfabricum.toml

ENV OSFABRICUM_DB_URL=sqlite:////data/osfabricum.db
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=20s \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["sh", "-c", "\
  alembic upgrade head && \
  uvicorn apps.api.app:app --host 0.0.0.0 --port 8000 & \
  osfabricum-worker \
    --db-url sqlite:////data/osfabricum.db \
    --worker-id worker-01 \
    --kinds 'build.run,package.build,rootfs.compose,image.compose' \
    --tags \"arch:$(uname -m)\" & \
  wait"]
