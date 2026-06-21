FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc make bc flex bison \
    libssl-dev libelf-dev libncurses-dev \
    libc6-dev \
    xz-utils bzip2 \
    && rm -rf /var/lib/apt/lists/*

COPY vendor/ vendor/
RUN pip install --no-cache-dir vendor/*.whl

COPY . .
RUN pip install --no-cache-dir -e ".[dev]" asyncpg psycopg2-binary

RUN mkdir -p /data /var/lib/osfabricum /etc/osfabricum && \
    printf '[database]\nurl = "sqlite+aiosqlite:////data/osfabricum.db"\n' \
    > /etc/osfabricum/osfabricum.toml

# Default: SQLite (overridden by OSFABRICUM_DB_URL in docker-compose)
ENV OSFABRICUM_DB_URL=sqlite+aiosqlite:////data/osfabricum.db
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=20s \
  CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["sh", "-c", "\
  SYNC_DB=$(echo \"$OSFABRICUM_DB_URL\" | sed 's/+aiosqlite//g;s/+asyncpg//g') && \
  alembic upgrade head && \
  uvicorn apps.api.app:app --host 0.0.0.0 --port 8000 & \
  while true; do \
    osfabricum-worker \
      --db-url \"$SYNC_DB\" \
      --worker-id worker-01 \
      --kinds 'build.run,package.build,rootfs.compose,image.compose' \
      --tags \"arch:$(uname -m)\"; \
    sleep 3; \
  done & \
  wait"]
