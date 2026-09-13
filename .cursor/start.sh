#!/usr/bin/env bash
#
# Per-boot startup for the FastCAT dev environment.
# Launches the local SQL Server instance (no systemd in the container), waits
# for it to accept connections, and ensures the FastCAT database exists.
# Idempotent: re-running while the server is up is a no-op besides the DB check.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQLCMD=/opt/mssql-tools18/bin/sqlcmd

# shellcheck source=.cursor/sa-password.sh
source "$REPO_ROOT/.cursor/sa-password.sh"

if ! pgrep -x sqlservr >/dev/null 2>&1; then
  echo "==> Starting SQL Server (sqlservr)"
  sudo -u mssql nohup /opt/mssql/bin/sqlservr >/tmp/mssql.log 2>&1 &
else
  echo "==> SQL Server already running"
fi

echo "==> Waiting for SQL Server to accept connections"
ready=0
for _ in $(seq 1 60); do
  if "$SQLCMD" -S 127.0.0.1 -U sa -P "$MSSQL_SA_PASSWORD" -C -l 2 -Q "SELECT 1" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done

if [ "$ready" != "1" ]; then
  echo "ERROR: SQL Server did not become ready in time. See /tmp/mssql.log" >&2
  exit 1
fi

echo "==> Ensuring FastCAT database exists"
"$SQLCMD" -S 127.0.0.1 -U sa -P "$MSSQL_SA_PASSWORD" -C \
  -Q "IF DB_ID('FastCAT') IS NULL CREATE DATABASE [FastCAT];"

echo "==> SQL Server ready; FastCAT database present."
