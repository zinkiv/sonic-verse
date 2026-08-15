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

Do **not** recursively chown a large `/music` tree. On start, `entrypoint.sh` runs as root, `chown`s `/data` to `PUID`/`PGID` (default **1000**), then drops privileges with `gosu`. Set these to the owner of the music/data mounts so tag writes succeed.

**Transfer inbox:** after dumping files via SMB as another user, restart once so entrypoint can re-`chown` `/data/transfer`.

## Environment variables

Paths (`/music`, `/data`, `/data/transfer`, `/app/logs`, `/app/web`) are handled inside `entrypoint.sh`. `PUID`/`PGID` are image ENV so NAS panels list them.

| Variable | Required | Description |
|----------|----------|-------------|
| `SERVER_PORT` | No (default `7526`) | Port inside the container |
| `DATABASE_URL` | No (empty → sqlite) | Postgres URL selects PostgreSQL, e.g. `postgres://user:pass@host:5432/db?sslmode=prefer` |
| `APP_VERSION` | No | Version shown in Settings (image bakes git tag at build; override at runtime if needed) |
| `AUTH_SECRET` | No | Login token secret. Empty: persist one under `/data/.auth_secret` |
| `PUID` | No (default `1000`) | User id the process runs as |
| `PGID` | No (default `1000`) | Group id the process runs as (`GUID` / `PGUID` also accepted) |
| `DEBUG` | No (default `false`) | Verbose logs |

Leave `DATABASE_URL` empty for local SQLite under `/data/database`. Set a `postgres://` / `postgresql://` URL to use PostgreSQL.

## Build & push

Pass the version at build time so Settings → Version shows it (default `dev` if omitted):

```powershell
$env:APP_VERSION = "v0.1.0"
docker compose build
docker push zevenz/sonic-verse:latest
```

Or from the current git tag:

```powershell
$env:APP_VERSION = (git describe --tags --always --dirty)
docker compose build
docker push zevenz/sonic-verse:latest
```

```bash
# bash
APP_VERSION=v0.1.0 docker compose build
# or
APP_VERSION=$(git describe --tags --always --dirty) docker compose build
docker push zevenz/sonic-verse:latest
```

Optional runtime override (compose / NAS panel): set `APP_VERSION=v1.2.3`.

## Source

https://github.com/zinkiv/sonic-verse
https://git.zeven.site/zeven/sonic-verse
