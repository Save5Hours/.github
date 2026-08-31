#!/bin/sh
# Import/patch the Save 5 Hours meeting-notes workflow, then start n8n.
# Never run n8n CLI as root against /home/node/.n8n (that writes /root/.n8n).
set -e

# Railway volumes are often root-owned on first attach. n8n must run as node.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /home/node/.n8n
  chown -R node:node /home/node/.n8n
  if command -v gosu >/dev/null 2>&1; then
    exec gosu node "$0" "$@"
  fi
  if command -v su-exec >/dev/null 2>&1; then
    exec su-exec node "$0" "$@"
  fi
  exec su -s /bin/sh node -c 'exec /opt/save5hours/n8n-boot.sh "$@"' -- "$@"
fi

export N8N_USER_FOLDER="${N8N_USER_FOLDER:-/home/node/.n8n}"
mkdir -p "$N8N_USER_FOLDER"

if [ -f /opt/save5hours/n8n-provision.mjs ]; then
  node /opt/save5hours/n8n-provision.mjs || echo "save5hours: provision deferred until next boot" >&2
fi

exec /docker-entrypoint.sh "$@"
