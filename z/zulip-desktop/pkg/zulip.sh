#!/usr/bin/env sh

# Make script fail if `cat` fails for some reason
set -e

# Wayland auto-detection. If the session is a wayland session then this will launch as a Wayland window unless the ZULIP_NO_WAYLAND variable is set
if [ -z "${ZULIP_NO_WAYLAND+set}" ]; then
  if [ -z "${ELECTRON_OZONE_PLATFORM_HINT+set}" ]; then
    export ELECTRON_OZONE_PLATFORM_HINT="auto"
  fi
fi

exec /usr/lib/zulip-desktop/zulip $ZULIP_FLAGS "$@"
