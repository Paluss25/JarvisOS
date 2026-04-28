#!/bin/bash
# Container entrypoint — runs before supervisord starts.
# Copies SSH files from the shared volume with correct root ownership.
set -e

SSH_SRC="/app/shared/ssh"
SSH_DST="/root/.ssh"

if [ -d "$SSH_SRC" ]; then
    mkdir -p "$SSH_DST"
    for f in config known_hosts; do
        if [ -f "$SSH_SRC/$f" ]; then
            cp "$SSH_SRC/$f" "$SSH_DST/$f"
            chmod 600 "$SSH_DST/$f"
        fi
    done
fi

exec supervisord -c /etc/supervisor/supervisord.conf
