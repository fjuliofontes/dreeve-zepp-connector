#!/bin/sh
set -e

# Default: run the continuous polling daemon (loop.py). To do a one-shot run
# instead, override the container command, e.g.:
#   docker run --rm --env-file .env -v ./output:/data <image> \
#     uv run dreeve-zepp-connector --dry-run
if [ "$#" -eq 0 ]; then
    exec uv run dreeve-zepp-connector-loop
fi

exec "$@"
