#!/usr/bin/env bash
#
# Idempotent environment bootstrap for the FastCAT Results Database project.
# Installs the system + Python dependencies the scripts need on Ubuntu 24.04:
#   - Microsoft ODBC Driver 17 & 18 for SQL Server + unixODBC
#   - Microsoft SQL Server 2022 (Developer edition) as a local dev database
#   - Google Chrome (for Selenium-based scrapers), if not already present
#   - A Python virtualenv (.venv) with everything in requirements.txt
#
# Safe to run repeatedly. Heavy/stable work belongs here so it is captured in
# the environment build snapshot; per-boot service startup lives in start.sh.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> [1/7] Base system packages"
sudo apt-get update -qq
sudo apt-get install -y -qq \
  curl gnupg ca-certificates apt-transport-https \
  unixodbc unixodbc-dev build-essential gcc g++ \
  python3 python3-venv python3-dev openssl

echo "==> [2/7] Microsoft package signing key + apt repositories"
if [ ! -f /usr/share/keyrings/microsoft-prod.gpg ]; then
  curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
    | sudo gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
fi
# ODBC drivers + mssql-tools (Ubuntu 24.04 / noble feed)
echo "deb [arch=amd64,arm64,armhf signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/ubuntu/24.04/prod noble main" \
  | sudo tee /etc/apt/sources.list.d/mssql-release.list >/dev/null
# SQL Server 2022 engine (published for jammy; runs on 24.04 with the shim below)
echo "deb [arch=amd64,arm64,armhf signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/ubuntu/22.04/mssql-server-2022 jammy main" \
  | sudo tee /etc/apt/sources.list.d/mssql-server-2022.list >/dev/null
sudo apt-get update -qq

echo "==> [3/7] ODBC drivers, tools, and SQL Server engine"
sudo ACCEPT_EULA=Y apt-get install -y -qq msodbcsql18 msodbcsql17 mssql-tools18 mssql-server

echo "==> [4/7] libldap 2.5 compatibility shim (SQL Server 2022 on Ubuntu 24.04)"
# SQL Server 2022 links against OpenLDAP 2.5, which ships on Ubuntu 22.04 but not
# 24.04. Pull just the two shared objects from the 22.04 archive.
if [ ! -e /usr/lib/x86_64-linux-gnu/liblber-2.5.so.0 ]; then
  shim_dir="$(mktemp -d)"
  (
    cd "$shim_dir"
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://security.ubuntu.com/ubuntu jammy-security main" \
      | sudo tee /etc/apt/sources.list.d/jammy-openldap-shim.list >/dev/null
    sudo apt-get update -qq
    apt-get download libldap-2.5-0
    dpkg-deb -x libldap-2.5-0*.deb extracted
    sudo cp -av extracted/usr/lib/x86_64-linux-gnu/liblber-2.5.so.0* /usr/lib/x86_64-linux-gnu/
    sudo cp -av extracted/usr/lib/x86_64-linux-gnu/libldap-2.5.so.0* /usr/lib/x86_64-linux-gnu/
    sudo rm -f /etc/apt/sources.list.d/jammy-openldap-shim.list
    sudo apt-get update -qq
  )
  sudo ldconfig
  rm -rf "$shim_dir"
fi

echo "==> [5/7] Google Chrome for Selenium (skip if already installed)"
if ! command -v google-chrome >/dev/null 2>&1 && ! command -v google-chrome-stable >/dev/null 2>&1; then
  curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
    | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
  echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    | sudo tee /etc/apt/sources.list.d/google-chrome.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq google-chrome-stable
fi

echo "==> [6/7] Configure SQL Server (idempotent, unattended)"
# shellcheck source=.cursor/sa-password.sh
source "$REPO_ROOT/.cursor/sa-password.sh"
sudo MSSQL_SA_PASSWORD="$MSSQL_SA_PASSWORD" ACCEPT_EULA=Y MSSQL_PID=Developer \
  /opt/mssql/bin/mssql-conf -n setup >/dev/null 2>&1 || true
sudo chown -R mssql:mssql /var/opt/mssql 2>/dev/null || true

echo "==> [7/7] Python virtualenv + dependencies"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip -q
pip install -q -r requirements.txt

echo "==> install.sh complete"
