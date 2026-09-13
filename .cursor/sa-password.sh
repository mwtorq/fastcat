#!/usr/bin/env bash
# Resolve the local SQL Server "sa" password without committing any secret.
#
# Precedence:
#   1. $MSSQL_SA_PASSWORD (e.g. a Cursor secret) if set.
#   2. A previously generated value cached in .cursor/.mssql_sa_password.
#   3. A freshly generated strong password, cached for reuse (gitignored).
#
# Sourced by install.sh and start.sh. Exports MSSQL_SA_PASSWORD.

_sa_password_repo_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

resolve_sa_password() {
  local repo_root pass_file
  repo_root="$(_sa_password_repo_root)"
  pass_file="$repo_root/.cursor/.mssql_sa_password"

  if [ -n "${MSSQL_SA_PASSWORD:-}" ]; then
    :
  elif [ -f "$pass_file" ]; then
    MSSQL_SA_PASSWORD="$(cat "$pass_file")"
  else
    # SQL Server requires a strong password (>=8 chars, mixed classes).
    MSSQL_SA_PASSWORD="Dev_$(openssl rand -hex 12)_Ok1"
    ( umask 077; printf '%s' "$MSSQL_SA_PASSWORD" > "$pass_file" )
  fi
  export MSSQL_SA_PASSWORD
}

resolve_sa_password
