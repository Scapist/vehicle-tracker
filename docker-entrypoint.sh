#!/bin/sh
# Starts as root only long enough to make /data writable for the app user, then drops privileges.
# Needed because ./data is a bind mount: its owner comes from the host (or an older root-run image),
# and a chown baked into the image doesn't apply to it.
set -e
APP_UID=10001
APP_GID=10001

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data
    if [ "$(stat -c %u /data)" != "$APP_UID" ] || [ -n "$(find /data ! -user "$APP_UID" -print -quit)" ]; then
        echo "entrypoint: giving /data to uid $APP_UID"
        chown -R "$APP_UID:$APP_GID" /data
    fi
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups --inh-caps=-all "$@"
fi
exec "$@"
