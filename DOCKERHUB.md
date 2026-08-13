# SonicVerse

Personal music-library metadata manager. Match tags from NetEase Cloud Music / QQ Music, write covers and artist images, organize files — one Docker container, SQLite included.

## Quick start

```yaml
name: sonic-verse

services:
  sonicverse:
    image: zevenz/sonic-verse:latest
    container_name: sonicverse
    ports:
      - "7526:7526"
    environment:
      # DATABASE_TYPE: postgresql
      # DATABASE_URL: postgres://user:password@host:5432/sonic_verse?sslmode=prefer
    volumes:
      - /volume1/music:/music
      - /volume1/docker/sonic-verse:/data
    restart: unless-stopped
```

```bash
docker compose up -d
```

Open: http://localhost:7526

## Volumes

| Path | Purpose |
|------|---------|
| `/music` | Music library |
| `/data` | SQLite, covers, transfer inbox (`/data/transfer`), library fingerprint, settings |

Do **not** recursively chown a large `/music` tree. On start, `entrypoint.sh` runs as root, `chown`s `/data` to uid/gid **1000**, then drops privileges with `gosu`. Ensure the host user that writes into the mounts can work with that ownership (or override `PUID`/`PGID` only if you know you need to).

**Transfer inbox:** after dumping files via SMB as another user, restart once so entrypoint can re-`chown` `/data/transfer`.

## Environment variables

Paths (`/music`, `/data`, `/data/transfer`, `/app/logs`, `/app/web`) and process uid/gid are handled inside `entrypoint.sh` — they are **not** listed as image ENV for NAS panels.

| Variable | Required | Description |
|----------|----------|-------------|
| `SERVER_PORT` | No (default `7526`) | Port inside the container |
| `DATABASE_TYPE` | No (default empty → sqlite) | `sqlite` or `postgresql` |
| `DATABASE_URL` | No | Postgres URL, e.g. `postgres://user:pass@host:5432/db?sslmode=prefer` |
| `DEBUG` | No (default `false`) | Verbose logs |

With `DATABASE_TYPE=postgresql`, set `DATABASE_URL`. A `postgres://` / `postgresql://` URL alone is enough to select PostgreSQL.

## Build & push

```bash
docker compose build
docker push zevenz/sonic-verse:latest
```

## Source

https://github.com/zevenz/sonic-verse
