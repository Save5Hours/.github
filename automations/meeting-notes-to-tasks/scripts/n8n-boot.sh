#!/bin/sh
# Import the Save 5 Hours meeting-notes workflow once per JSON revision,
# then start n8n via the upstream entrypoint.
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

WF="/opt/save5hours/meeting-notes-to-tasks.json"
MARKER_DIR="/home/node/.n8n"
mkdir -p "$MARKER_DIR"
if [ -f "$WF" ]; then
  HASH="$(sha256sum "$WF" | awk '{print $1}')"
  MARKER="$MARKER_DIR/.save5hours-wf-$HASH"
  if [ ! -f "$MARKER" ]; then
    if n8n import:workflow --input="$WF"; then
      touch "$MARKER"
    else
      echo "save5hours: workflow import deferred until next boot" >&2
    fi
  fi
fi
exec /docker-entrypoint.sh "$@"
