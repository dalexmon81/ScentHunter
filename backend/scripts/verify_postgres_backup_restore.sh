#!/usr/bin/env bash
# Disposable-local PostgreSQL backup/restore rehearsal.
# Refuses remote hosts and non-ci_restore_* targets to prevent production use.
set -euo pipefail

: "${SCENTHUNTER_CATALOG_DATABASE_URL:?source PostgreSQL URL is required}"
: "${SCENTHUNTER_BACKUP_RESTORE_TARGET_URL:?restore target URL is required}"
[[ "${SCENTHUNTER_BACKUP_RESTORE_CONFIRM:-}" == "DISPOSABLE_CI_ONLY" ]] || {
  echo "Refusing backup/restore rehearsal without explicit disposable-CI confirmation." >&2
  exit 2
}

source_url="${SCENTHUNTER_CATALOG_DATABASE_URL/+psycopg/}"
target_url="${SCENTHUNTER_BACKUP_RESTORE_TARGET_URL/+psycopg/}"

readarray -t db_parts < <(python3 - "$source_url" "$target_url" <<'PY'
import sys
from urllib.parse import urlparse

source, target = map(urlparse, sys.argv[1:])
for label, parsed in (("source", source), ("target", target)):
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise SystemExit(f"{label} must be PostgreSQL")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(f"Refusing non-loopback {label} host")
source_db = source.path.lstrip("/")
target_db = target.path.lstrip("/")
if not source_db or not target_db or source_db == target_db:
    raise SystemExit("Source and target databases must be distinct and named")
if not target_db.startswith("ci_restore_"):
    raise SystemExit("Restore target database name must start with ci_restore_")
if (source.hostname, source.port, source.username) != (target.hostname, target.port, target.username):
    raise SystemExit("Source and restore target must use the same local PostgreSQL service")
print(source_db)
print(target_db)
PY
)
source_db="${db_parts[0]}"
target_db="${db_parts[1]}"

command -v pg_dump >/dev/null
command -v pg_restore >/dev/null
command -v createdb >/dev/null
command -v dropdb >/dev/null
command -v psql >/dev/null

backup_dir="$(mktemp -d)"
backup_file="$backup_dir/scenthunter-catalog.dump"
cleanup() {
  dropdb --if-exists --maintenance-db="$source_url" "$target_db" >/dev/null 2>&1 || true
  rm -rf "$backup_dir"
}
trap cleanup EXIT

pg_dump --format=custom --no-owner --no-acl --file="$backup_file" "$source_url"
test -s "$backup_file"
createdb --maintenance-db="$source_url" "$target_db"
pg_restore --no-owner --no-acl --exit-on-error --dbname="$target_url" "$backup_file"

source_snapshot="$(psql "$source_url" -v ON_ERROR_STOP=1 -Atc "SELECT (SELECT count(*) FROM brands), (SELECT count(*) FROM fragrances), (SELECT count(*) FROM product_variants), (SELECT version_num FROM alembic_version LIMIT 1)")"
restored_snapshot="$(psql "$target_url" -v ON_ERROR_STOP=1 -Atc "SELECT (SELECT count(*) FROM brands), (SELECT count(*) FROM fragrances), (SELECT count(*) FROM product_variants), (SELECT version_num FROM alembic_version LIMIT 1)")"

[[ "$source_snapshot" == "$restored_snapshot" ]] || {
  echo "Backup/restore mismatch: source=$source_snapshot restored=$restored_snapshot" >&2
  exit 1
}
[[ "${source_snapshot%%,*}" -gt 0 ]] || {
  echo "Source catalog is unexpectedly empty; refusing to accept the rehearsal." >&2
  exit 1
}

echo "POSTGRES_BACKUP_RESTORE=PASS source_db=$source_db target_db=$target_db snapshot=$source_snapshot"
