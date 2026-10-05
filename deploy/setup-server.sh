#!/usr/bin/env bash
# WCC Launchpad -- one-command production setup for a fresh Ubuntu 22.04/24.04
# server. Run from the project folder, as root:
#
#     sudo bash deploy/setup-server.sh                  # free sslip.io address
#     sudo bash deploy/setup-server.sh launchpad.my.xyz # your own domain
#
# What it does (safe to re-run; it never overwrites values you've set):
#   1. installs Docker (official script) if missing
#   2. adds 2 GB of swap on small servers (the frontend build needs RAM)
#   3. opens only SSH, HTTP and HTTPS in the firewall
#   4. fills in .env for production: domain, public URL, strong secrets,
#      nginx bound to localhost only
#   5. builds and starts everything with automatic HTTPS (Caddy)
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f docker-compose.yml ] || { echo "Run this from the wcc-launchpad folder."; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "Please run as root: sudo bash deploy/setup-server.sh"; exit 1; }

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- 1. Docker
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null

# ---------------------------------------------------------------- 2. Swap
mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$mem_mb" -lt 3500 ] && ! swapon --show | grep -q .; then
  say "Adding 2 GB swap (server has ${mem_mb} MB RAM)"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---------------------------------------------------------------- 3. Firewall
if command -v ufw >/dev/null 2>&1; then
  say "Firewall: allowing SSH, HTTP, HTTPS only"
  ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw allow 443/udp >/dev/null
  ufw --force enable >/dev/null
fi

# ---------------------------------------------------------------- 4. .env
[ -f .env ] || cp .env.example .env

get_env() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
set_env() {  # set_env KEY VALUE  (replace or append)
  if grep -qE "^$1=" .env; then
    python3 - "$1" "$2" <<'PY'
import sys, re
k, v = sys.argv[1], sys.argv[2]
s = open(".env").read()
s = re.sub(rf"(?m)^{re.escape(k)}=.*$", lambda m: f"{k}={v}", s)
open(".env", "w").write(s)
PY
  else
    echo "$1=$2" >> .env
  fi
}
rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }

domain="${1:-$(get_env DOMAIN)}"
if [ -z "$domain" ]; then
  ip=$(curl -fsS https://api.ipify.org || curl -fsS https://ifconfig.me)
  domain="${ip//./-}.sslip.io"
  say "No domain given: using the free address $domain (points to $ip)"
fi
set_env DOMAIN "$domain"
set_env PUBLIC_BASE_URL "https://$domain"
set_env HOST_PORT "127.0.0.1:8080"
set_env ENVIRONMENT "production"

if [ "$(get_env JWT_SECRET)" = "change_this_in_production" ] || [ -z "$(get_env JWT_SECRET)" ]; then
  say "Generating a strong JWT_SECRET (also signs certificates)"
  set_env JWT_SECRET "$(rand 48)"
fi
# Only change the database password before the database exists; changing it
# afterwards would lock the app out of its own data.
if [ "$(get_env POSTGRES_PASSWORD)" = "launchpad_dev_password" ] && ! docker volume inspect wcc-launchpad_postgres_data >/dev/null 2>&1; then
  say "Generating a strong database password"
  set_env POSTGRES_PASSWORD "$(rand 24)"
fi

# ---------------------------------------------------------------- 5. Start
say "Building and starting (first build takes 3-6 minutes)"
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

say "Waiting for the app to come up"
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1; then break; fi
  sleep 5
done
curl -fsS http://127.0.0.1:8080/api/health >/dev/null || { echo "App didn't start; see: docker compose logs backend"; exit 1; }

say "Waiting for the HTTPS certificate"
for _ in $(seq 1 24); do
  if curl -fsS "https://$domain/api/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 5
done

echo
if [ "${ok:-0}" = 1 ]; then
  printf '\033[1;32mLIVE:  https://%s\033[0m\n' "$domain"
else
  echo "The app is running, but HTTPS isn't answering yet for $domain."
  echo "Check that the domain's DNS points to this server, then: docker compose logs caddy"
fi
echo
docker compose logs backend 2>/dev/null | grep -A 12 "demo accounts" | tail -n 12 || true
echo
echo "Email: set SENDGRID_API_KEY and MAIL_FROM in .env, then re-run this script."
