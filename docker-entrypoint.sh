#!/bin/sh
set -e

# Default: run the continuous polling daemon (loop.py). To do a one-shot run
# instead, override the container command, e.g.:
#   docker run --rm --env-file .env -v ./output:/watch -v ./state:/state <image> \
#     uv run --frozen --no-dev dreeve-zepp-connector --dry-run
#
# --frozen --no-dev: use the venv exactly as built into the image (matching
# the Dockerfile's build-time `uv sync --frozen --no-dev`) - otherwise plain
# `uv run` re-syncs at container startup and pulls in the dev dependency
# group (pytest, etc.), needing network access and installing packages the
# runtime never uses.
if [ "$#" -eq 0 ]; then
    exec uv run --frozen --no-dev dreeve-zepp-connector-loop
fi

exec "$@"
