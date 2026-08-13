#!/bin/sh
set -e

# Common typo on NAS panels
if [ -z "${PGID}" ] && [ -n "${PGUID}" ]; then
  PGID="${PGUID}"
fi

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
SERVER_PORT="${SERVER_PORT:-7526}"

# Fixed container layout — not image ENV, so NAS panels do not list them.
export WEB_DIR=/app/web
export DATA_PATH=/data
export MUSIC_PATH=/music
export TRANSFER_PATH=/data/transfer
export LOGS_PATH=/app/logs

# True when local SQLite under /data/database should be used.
uses_sqlite_db() {
  type_lc=$(printf '%s' "${DATABASE_TYPE:-}" | tr '[:upper:]' '[:lower:]')
  url="${DATABASE_URL:-}"
  case "${url}" in
    postgres://*|postgresql://*|postgresql+asyncpg://*)
      return 1
      ;;
  esac
  case "${type_lc}" in
    postgresql|postgres)
      return 1
      ;;
  esac
  return 0
}

database_label() {
  if uses_sqlite_db; then
    echo "${DATABASE_TYPE:-sqlite}"
  else
    echo "postgresql"
  fi
}

ensure_dirs() {
  mkdir -p \
    "${DATA_PATH}/covers" \
    "${DATA_PATH}/library" \
    "${TRANSFER_PATH}" \
    "${LOGS_PATH}" \
    "${MUSIC_PATH}"
  # SQLite file lives here; skip when DATABASE_URL/TYPE points at PostgreSQL.
  if uses_sqlite_db; then
    mkdir -p "${DATA_PATH}/database"
  fi
}

fix_data_ownership() {
  if [ "$(id -u)" != "0" ]; then
    return 0
  fi
  if [ "${PUID}" = "0" ] && [ "${PGID}" = "0" ]; then
    return 0
  fi

  # Files dropped via SMB/AFP often arrive owned by another NAS user.
  # Re-assert ownership on every start so tag writes under /data/transfer work.
  if ! chown -R "${PUID}:${PGID}" "${DATA_PATH}"; then
    echo "sonicverse: WARNING — could not chown ${DATA_PATH} to ${PUID}:${PGID}." >&2
    echo "Tag writes may fail for files owned by other users." >&2
  fi
  chown -R "${PUID}:${PGID}" "${LOGS_PATH}" 2>/dev/null || true

  # Owner write on transfer inbox (and nested files).
  chmod u+rwx "${TRANSFER_PATH}" 2>/dev/null || true
  find "${TRANSFER_PATH}" -type d -exec chmod u+rwx {} \; 2>/dev/null || true
  find "${TRANSFER_PATH}" -type f -exec chmod u+rw {} \; 2>/dev/null || true
}

require_writable_data() {
  if [ -w "${DATA_PATH}" ]; then
    return 0
  fi
  echo "sonicverse: ${DATA_PATH} is not writable (uid=$(id -u) gid=$(id -g))." >&2
  echo "Check PUID/PGID and host directory permissions." >&2
  exit 1
}

run_app() {
  exec uvicorn sonicverse.main:app --host 0.0.0.0 --port "${SERVER_PORT}"
}

echo "----------------------------------------"
echo "SonicVerse"
echo "User UID:    ${PUID}"
echo "User GID:    ${PGID}"
echo "Port:        ${SERVER_PORT}"
echo "Database:    $(database_label)"
echo "Data path:   ${DATA_PATH}"
echo "Logs path:   ${LOGS_PATH}"
echo "Music path:  ${MUSIC_PATH}"
echo "Transfer:    ${TRANSFER_PATH}"
echo "----------------------------------------"

ensure_dirs

if [ "$(id -u)" = "0" ]; then
  fix_data_ownership
  if [ "${PUID}" = "0" ] && [ "${PGID}" = "0" ]; then
    require_writable_data
    run_app
  fi
  require_writable_data
  exec gosu "${PUID}:${PGID}" uvicorn sonicverse.main:app --host 0.0.0.0 --port "${SERVER_PORT}"
fi

require_writable_data
run_app
