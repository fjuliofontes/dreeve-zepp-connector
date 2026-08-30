# dreeve-zepp-connector

Pulls workouts from your Zepp / Amazfit cloud account and writes them as
`.FIT` files into a local folder — intended to be [Dreeve](https://github.com/dreeveapp/dreeve)'s
watch folder, alongside its existing [Garmin connector](https://github.com/dreeveapp/dreeve-garmin-connector).

Unlike the Garmin connector, Zepp's API has no native `.FIT` export — this
tool decodes Zepp's raw per-sample track data (GPS, heart rate, altitude,
cadence for both running and swimming, speed, running power, step length,
per-kilometer splits) and synthesizes a `.FIT` file from it.

## Status

v1 (one-shot CLI) plus v2's daemon-hardening: Docker packaging, a continuous
polling loop with health endpoints, API rate-limit backoff, and per-cycle
download throttling.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A Zepp / Amazfit account (email + password login)

## Setup

```bash
uv sync
cp .env.example .env   # then add your Zepp credentials and watch dir
```

## Configuration

```ini
ZEPP_EMAIL=you@example.com
ZEPP_PASSWORD=your-zepp-password
WATCH_DIR=/path/to/dreeve/watch-folder
STATE_DIR=/path/to/state
SINCE=-30d
```

`WATCH_DIR` and `STATE_DIR` are deliberately separate: `WATCH_DIR` is where
`.FIT` files land (point it at Dreeve's watch folder — nothing else should
be in there), `STATE_DIR` is where the ledger file lives (default
`./state`; `LEDGER_PATH` overrides its exact file path if you need it
somewhere else entirely).

`SINCE` (or `--since`) sets where import starts from — useful if you've
already imported older history some other way and just want to pick up from
a point in time. Accepts an ISO date (`2026-07-24`), a relative offset
(`-30d`), or `all` (default — no lower bound, subject to `--limit`).
Already-exported workouts are tracked in the ledger and always skipped on
later runs regardless of `SINCE`. That same ledger file also caches the
login token after a successful run, so later runs skip logging in again
until the cached token is actually rejected — it's written `0600` since it
now holds a live credential.

`ZEPP_DEVICE_NAMES` (optional) maps device IDs to names for each `.FIT`
file's device info. Zepp's API doesn't expose the recording device's model
anywhere in workout data, so this can't be auto-detected — leave it unset
and files just won't carry a device name. Format: `<device_id>=<name>`,
semicolon-separated for accounts with more than one watch. To find your
device ID(s), run `uv run dreeve-zepp-connector --dry-run` — it prints each
workout as `(dry-run) would export ... (device_id=9568513)` without
exporting anything.

## Usage

```bash
uv run python -m dreeve_zepp_connector --dry-run
uv run python -m dreeve_zepp_connector
uv run python -m dreeve_zepp_connector --since -30d          # only the last 30 days
uv run python -m dreeve_zepp_connector --since 2026-07-24    # only from this date on
```

`--limit` (default 200, or `LIMIT` env var) caps the total number of
workouts considered, paging back through Zepp's history as needed to satisfy
`--since` — raise it if you have more than 200 workouts within the window
you're importing.

## Running continuously (Docker)

For unattended/scheduled use, `dreeve-zepp-connector-loop` (also
`python -m dreeve_zepp_connector.loop`) runs the same fetch+export cycle as
the one-shot CLI on a `POLL_INTERVAL` cadence, and is the default Docker
command:

```bash
cp .env.example .env   # add credentials as above
docker compose up -d
curl http://localhost:8080/healthz   # {"status": "ok"}
curl http://localhost:8080/status    # last cycle's result, error, cycle count
```

`docker-compose.yml` mounts `./output` as the container's `/watch`
(`WATCH_DIR`) and `./state` as `/state` (`STATE_DIR`). The published host
port also comes from `HEALTH_PORT` (`.env`, default 8080) — e.g. set
`HEALTH_PORT=9090` there if 8080 is already taken on your host, no compose
file edits needed; it's the same variable the container listens on
internally, so host and container ports always match. If you don't need to
reach `/healthz`/`/status` from outside the container at all, you can
remove `docker-compose.yml`'s `ports:` section entirely — Docker's own
`HEALTHCHECK` (visible via `docker ps`/`docker inspect`) runs inside the
container's network and doesn't need the port published.

To run a one-shot command in the container instead of the loop, override
the command:

```bash
docker compose run --rm dreeve-zepp-connector uv run --frozen --no-dev dreeve-zepp-connector --dry-run
```

Additional env vars for unattended/large-backfill use:

- `ZEPP_MAX_RETRIES` / `ZEPP_RETRY_BASE_DELAY` — retry Zepp API calls on
  connection errors and HTTP 429s with exponential backoff (defaults 5,
  2.0s; a 429's `Retry-After` header is honored if present).
- `DOWNLOAD_DELAY_SECONDS` — pause this long after each workout's detail is
  fetched (default 0).
- `MAX_DOWNLOADS_PER_CYCLE` — cap new workouts exported per run/cycle
  (default unlimited); anything past the cap rolls over to the next
  run/cycle automatically via the ledger. Useful so a large first-time
  backfill doesn't hammer the API in one go when run via the loop.

## Notes on the underlying (unofficial) API

This tool talks to `api-mifit.zepp.com` with plain query params (`trackid`,
`source`, `userid`) — confirmed working as of 2026-08. Two things worth
knowing if it ever stops working:

- **Regional hosts.** Live traffic from the official app has been observed
  hitting region-specific hosts too, e.g. `api-mifit-de2.zepp.com` for an
  EU-region account, rather than the unqualified `api-mifit.zepp.com` this
  tool uses. Login's `country_code` param (`ZEPP_COUNTRY` env var, default
  `US`) is separate from this — the unqualified data host has worked fine
  so far regardless of `ZEPP_COUNTRY`, but a region mismatch is the first
  thing to suspect if fetch calls start failing for a specific account.
- **A newer encrypted-payload scheme.** The same live traffic shows
  `/v1/sport/run/detail.json` being called with a single encrypted
  `cipher_data` query parameter instead of plaintext `trackid`/`source`/
  `userid` — likely a newer app-level request encryption layer. If the
  plaintext-param endpoint is ever retired, that's the scheme to
  reverse-engineer next; `huami-token`'s `mi_crypto.py` module (MIT,
  [codeberg.org/argrento/huami-token](https://codeberg.org/argrento/huami-token) —
  not a dependency of this project, just a reference) documents the broader
  Xiaomi/Huami encryption scheme and would be a starting point.

## Credits

- Zepp web-app login flow ported from
  [`effectpears/zepp-downloader`](https://github.com/effectpears/zepp-downloader)'s
  `zepp_app_token.py`.
- Data-call header identity ported from
  [`huami-token`](https://codeberg.org/argrento/huami-token) (MIT).
- Zepp track-data decoding ported from
  [`rolandsz/Mi-Fit-and-Zepp-workout-exporter`](https://github.com/rolandsz/Mi-Fit-and-Zepp-workout-exporter)
  (MIT), itself based on [`mireq/MiFitDataExport`](https://github.com/mireq/MiFitDataExport).

## Disclaimer

Unofficial client using a reverse-engineered Zepp cloud API. Not affiliated
with or endorsed by Zepp Health / Huami. Use with your own account, at your
own risk.
