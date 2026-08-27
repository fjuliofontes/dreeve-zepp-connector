# dreeve-zepp-connector

Pulls workouts from your Zepp / Amazfit cloud account and writes them as
`.FIT` files into a local folder — intended to be [Dreeve](https://github.com/dreeveapp/dreeve)'s
watch folder, alongside its existing [Garmin connector](https://github.com/dreeveapp/dreeve-garmin-connector).

Unlike the Garmin connector, Zepp's API has no native `.FIT` export — this
tool decodes Zepp's raw per-sample track data (GPS, heart rate, altitude,
cadence for both running and swimming, speed, running power, step length,
per-kilometer splits) and synthesizes a `.FIT` file from it.

## Status

Work in progress (v1: one-shot CLI, no daemon/Docker yet).

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A Zepp / Amazfit account (email + password login)

## Setup

```bash
uv sync
cp .env.example .env   # then add your Zepp credentials and output dir
```

## Configuration

```ini
ZEPP_EMAIL=you@example.com
ZEPP_PASSWORD=your-zepp-password
OUTPUT_DIR=/path/to/dreeve/watch-folder
SINCE=-30d
```

`SINCE` (or `--since`) sets where import starts from — useful if you've
already imported older history some other way and just want to pick up from
a point in time. Accepts an ISO date (`2026-07-24`), a relative offset
(`-30d`), or `all` (default — no lower bound, subject to `--limit`).
Already-exported workouts are tracked in a ledger file and always skipped on
later runs regardless of `SINCE`. That same ledger file also caches the
login token after a successful run, so later runs skip logging in again
until the cached token is actually rejected — it's written `0600` since it
now holds a live credential.

`ZEPP_DEVICE_NAMES` (optional) maps device IDs to names for each `.FIT`
file's device info. Zepp's API doesn't expose the recording device's model
anywhere in workout data, so this can't be auto-detected — leave it unset
and files just won't carry a device name. Format: `<device_id>=<name>`,
semicolon-separated for accounts with more than one watch. Find a
workout's `device_id` in its `devicesource` field (also embedded in
`source`, e.g. `run.9568513.huami.com` → `9568513`).

## Usage

```bash
uv run python -m dreeve_zepp_connector --dry-run
uv run python -m dreeve_zepp_connector
uv run python -m dreeve_zepp_connector --since -30d          # only the last 30 days
uv run python -m dreeve_zepp_connector --since 2026-07-24    # only from this date on
```

`--limit` (default 200) caps the total number of workouts considered, paging
back through Zepp's history as needed to satisfy `--since` — raise it if you
have more than 200 workouts within the window you're importing.

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
