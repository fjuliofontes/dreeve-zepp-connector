# dreeve-zepp-connector

## What this is

A standalone Python CLI (not an MCP server) that pulls workouts from a Zepp /
Amazfit cloud account and writes them as `.FIT` files into a local folder —
intended to be [Dreeve](https://github.com/dreeveapp/dreeve)'s watch folder,
alongside its existing [Garmin connector](https://github.com/dreeveapp/dreeve-garmin-connector).

Why this exists: Garmin Connect lets you download a device's *original*
`.FIT` file directly, so the Garmin connector just re-hosts a file Garmin
already produced. Zepp has no equivalent export — its cloud API only returns
JSON with per-sample track data encoded as delta-compressed strings. This
tool decodes that raw format and *synthesizes* a `.FIT` file from it.

Sibling project: `../zepp-mcp` (an MCP server exposing the same Zepp cloud
data to AI agents). This project ported and extended `zepp-mcp`'s auth/fetch
client rather than depending on it directly.

## Architecture (current, v1)

- **`zepp_client.py`** — Zepp cloud auth + fetch, ported from `zepp-mcp`'s
  `huami_client.py` with its token-saving truncation of GPS/HR/altitude
  fields removed (this project needs the full data). Login goes through
  Zepp's *web-app* flow (`com.huami.webapp`), not the `huami-token` lib's
  `ZeppSession` — see the "Login flow" quirk below. Paginates workout
  history via a `trackid` cursor (`workouts_page()`/`data.next`) — the API
  has no offset-based pagination.
- **`decoder.py`** — decodes Zepp's encoded `longitude_latitude` /
  `heart_rate` / `altitude` / `gait` / `time` fields into track points.
  Ported (with attribution) from the MIT-licensed
  `rolandsz/Mi-Fit-and-Zepp-workout-exporter`, itself based on
  `mireq/MiFitDataExport` — this is the one place the actual encoding
  scheme is documented; don't re-derive it from scratch.
- **`fit_writer.py`** — builds `.FIT` bytes via the `fit-tool` PyPI library.
  `TYPE_MAP` maps Zepp's numeric workout `type` codes to FIT `Sport`/
  `SubSport`. Synthesizes placeholder records for track-less workouts
  (strength, pool swims, table tennis, ...) — this is required, not
  optional (see Known quirks below).
- **`ledger.py`** — local JSON file (`OUTPUT_DIR/ledger.json`) tracking
  already-exported `trackid`s so re-runs skip them. Also caches the last
  successful `app_token`/`user_id` (keyed to `email`+`country`) so re-runs
  skip the login network round-trip entirely unless the cached token
  actually gets rejected — see "app_token caching" quirk below.
- **`main.py`** — CLI entrypoint (`--since`, `--limit`, `--output-dir`,
  `--dry-run`). Pages back through history until either the `--since`
  cutoff is covered or `--limit` total workouts are collected.

## Known quirks / gotchas

Documented here so they don't get silently re-broken or re-derived:

- **Zepp's encoding**: `time`, both halves of `longitude_latitude`, and
  `heart_rate`'s value column are delta-encoded (need cumulative sum);
  `altitude` and `gait`'s stride/cadence columns are absolute but sampled on
  their own irregular timestamps (need interpolation onto a unified
  timeline). Lat/lon scale ÷1e8, altitude in centimeters. `NO_VALUE =
  -2000000` is the sentinel for "no altitude reading at all."
- **Interpolation artifacts**: the ported decoder interpolates gaps using
  integer floor-division slopes (faithful to the upstream reference). Across
  a wide gap between real samples this can under/overshoot into physically
  impossible values (observed live: cadence of `-46`). `fit_writer._in_range`
  clamps/drops these per-field rather than crashing.
- **Mixed types from the API**: summary fields (`calorie`, `avg_heart_rate`,
  `type`) come back as a mix of ints, floats, and numeric strings like
  `"375.0"` across different workouts. Always route through `_to_int()`,
  never a bare `int(...)`.
- **Dreeve rejects record-less FIT files, unconditionally.** Confirmed
  against Dreeve's own `FitFileParser.php`: it throws `"No FIT 'record'
  messages found"` and rejects the file before it even looks at sport or
  session data, regardless of how complete the Session/Lap summary is. This
  is why `fit_writer.py` synthesizes a placeholder record stream (timestamp
  + repeated avg heart rate + a linear distance ramp) for any workout with
  no decoded GPS track — removing that would silently break every indoor/
  strength/pool-swim/racket-sport export again.
- **Login flow was switched off `huami-token`'s `ZeppSession` on
  2026-08-26.** `ZeppSession.login()` registers as an Android device
  (`app_name=com.huami.midong`, `device_model=android_phone`) and was found
  to log the user's phone app out as a side effect — unacceptable since the
  phone app is used alongside this connector. `zepp_client._web_login()`
  replaces it with Zepp's *web-app* login (`app_name=com.huami.webapp`,
  `device_model=web`), ported (with attribution) from
  `effectpears/zepp-downloader`'s `zepp_app_token.py` — three plain
  `requests` calls (registration -> access code -> login_token ->
  app_token) instead of `huami-token`'s encrypted mobile handshake.
  Confirmed live (2026-08-26) not to disconnect the phone app. `huami-token`
  is still a dependency, but now only for its `HEADERS.ZEPP_DEVICES`
  constant used on data calls — not for login. Login's `country_code`
  defaults to `"US"` (`ZEPP_COUNTRY` env var to override); the old
  `huami-token`-hardcoded-region quirk no longer applies to login, but a
  wrong `ZEPP_COUNTRY` is now the first thing to check if login itself
  starts failing for a specific account.
- **`app_token` caching (added 2026-08-26).** `main.py` checks
  `ledger.cached_auth()` before calling `client.login()` — if a token was
  cached from a prior run for the same `email`+`country`, it's handed to
  `client.use_cached_auth()` and the login network round-trip is skipped
  entirely. `ZeppDataClient._get()` detects a rejected/expired token via a
  401/403 response, drops it, and transparently re-logs-in once before
  replaying the failed call — no explicit expiry/TTL tracking, purely
  reactive. The refreshed (or first-ever) token is written back to
  `ledger.json` at the end of a non-dry-run. Because `ledger.json` now holds
  a live credential, `Ledger.save()` chmods it `0o600`; it was already
  gitignored. Note this doesn't apply to `--dry-run`, which never touches
  the ledger.
- **A newer, encrypted API variant exists.** Live app traffic has been
  observed calling region-specific hosts (e.g. `api-mifit-de2.zepp.com`)
  with a single encrypted `cipher_data` query param instead of this tool's
  plaintext `trackid`/`source`/`userid` params. Not implemented — the
  plaintext endpoint still works as of 2026-08 — but it's the lead to chase
  if that ever changes (see README's "Notes on the underlying API").
- **Ball/team sports go through the same endpoint.** Volleyball, table
  tennis, etc. all showed up via the normal `run/history.json` endpoint —
  there's no separate "ball games" API as first suspected. A workout
  "missing" from output is far more likely a wrong/stale `trackid` than a
  real API gap — verify directly against the account before assuming a new
  endpoint is needed.
- **`TYPE_MAP` coverage** (extend as new codes surface — an unmapped type
  prints a warning instead of failing silently):

  | code | sport | code | sport |
  |------|-------|------|-------|
  | 1 | running | 16 | free training (generic) |
  | 6 | walking | 17 | tennis |
  | 8 | treadmill | 49 | strength training |
  | 9 | outdoor cycling | 88 | volleyball |
  | 10 | indoor cycling | 89 | table tennis |
  | 14 | pool swimming | 140 | kayaking |
  | 15 | open water swimming | 223 | generic movement |

- **`--limit` default is 200.** A full historical backfill needs an
  explicit higher `--limit` (or `--since all --limit <N>`) — 200 is a
  reasonable cap for "catch up the last month or two" but will silently cap
  a deep backfill.

## V2 — pending, not yet built

v1 deliberately scoped to a one-shot CLI (see the conversation history /
original plan) rather than matching `dreeve-garmin-connector`'s full daemon
architecture. Still to build, roughly in priority order:

1. **Docker packaging** — `Dockerfile` + `docker-compose.yml` +
   `docker-entrypoint.sh`, matching the Garmin connector's layout, so this
   can run as a persistent service next to it.
2. **Scheduled/continuous polling** — a `loop.py` equivalent: run on a
   `POLL_INTERVAL` (env-configurable, default something like 3600s) instead
   of relying on external cron. Should reuse `main.py`'s `run()` internals,
   not duplicate them.
3. **Health/status endpoints** — `/healthz` and `/status` HTTP endpoints
   like the Garmin connector, for monitoring when run as a long-lived
   container.
4. **Rate-limit backoff** — exponential backoff on 429s from Zepp's API,
   plus a `DOWNLOAD_DELAY_SECONDS`-style throttle between per-workout
   `workout_detail()` calls (matters more once this runs unattended/on a
   schedule against a large history).
5. **`MAX_DOWNLOADS_PER_CYCLE`-style throttling** for large first-time
   backfills, so a fresh deploy against years of history doesn't hammer the
   API in one run — spread across cycles instead (same idea the Garmin
   connector's `.env.example` documents).
6. **Proper pool-swim fidelity (maybe)** — current synthetic-record
   approach gets swims past Dreeve's import gate and shows correct
   sport/duration/calories/avg-HR, but has no real per-length data
   (`LengthMessage`, `pool_length`, `num_lengths`, SWOLF). Investigate
   whether Zepp's API exposes lap-level swim data at all before investing
   here — unconfirmed either way.
7. **`cipher_data` endpoint support (fallback only)** — only needed if the
   current plaintext detail endpoint stops working; see the quirk above.

## Comparison: `effectpears/zepp-downloader` (reviewed 2026-08-24)

A friend independently released [zepp-downloader](https://github.com/effectpears/zepp-downloader)
(single-file script, tuned against an Amazfit Stratos 3), same goal as this
project. Full comparison done by cloning and reading its source; findings
below so they don't need re-deriving.

**What we do better:**
- Login via email/password vs. their original manual "pull the `apptoken`
  header out of devtools" flow — though as of 2026-08-26 our login flow
  itself now *is* their contributor's follow-up script, `zepp_app_token.py`
  (see the "Login flow" quirk above): it turned out `huami-token`'s
  `ZeppSession` login logs the phone app out, which their plain-`requests`
  web-app flow doesn't. We still keep the email/password UX (their
  companion script prompts once and caches the resulting `app_token`,
  ours logs in fresh each run); the underlying HTTP calls are now shared
  lineage.
- Real historical backfill: our `fetch_workouts()` pages back through
  history via the `trackid` cursor until `--since`/`--limit` is satisfied.
  Theirs only ever fetches the single most recent `FETCH_LIMIT` (default
  20) activities per run — no pagination, so it can only "catch up since
  last cron tick," not backfill deep history.
- Decoder fidelity: we delta-decode `time`, `heart_rate`, and both lat/lon
  halves, and interpolate `altitude`/`gait` onto a unified timeline. Theirs
  treats `heart_rate` as a flat non-delta int list — likely wrong for
  devices/accounts where HR is delta-encoded like ours documents above.
- Track-less workout placeholders: both synthesize records (Dreeve
  requires a non-empty `record` stream), but ours ramps 60 points with
  HR+distance; theirs only emits 1–2 records.

**Real gaps worth considering (not yet acted on):**
- No retry/backoff on HTTP calls at all in our `zepp_client._get()` — a
  single flaky request just fails that workout. Theirs retries with
  exponential backoff and gives specific 401/403/429 messages. Overlaps
  with V2 item 4 below but is currently *fully unbuilt*, not just
  unthrottled.
- No lock file (`fcntl.flock`) preventing two overlapping runs from racing
  on the ledger/output dir — matters once V2's scheduled polling exists.
- No rotating file log (we only `print()`) — would help debugging once
  this runs headless via cron/Docker.
- `TYPE_MAP` coverage: they map several codes we don't — 7 (trail run), 11
  (elliptical), 12 (indoor rowing), 13/16 (mountaineering), 18 (alpine
  skiing), 19 (cross-country skiing), 20 (snowboarding), 24 (indoor
  fitness), 27 (yoga), 39 (triathlon/multisport, with a `type % 1000`
  prefix-strip for `1000 < type < 2000` composite-activity legs that we
  don't handle at all).

**⚠️ Type-code conflict to investigate — do not blindly merge their table:**
their code **17 = HIKING**; ours (`fit_writer.TYPE_MAP`) has **17 =
TENNIS**. Their script was tuned specifically for an Amazfit Stratos 3, so
`type` codes may not be portable 1:1 across devices/firmware/app versions —
same numeric code could mean different things depending on device
generation. Before importing any of their mapping, verify actual `type`
values seen from the account in question (per the "Ball/team sports" quirk
above: confirm against real API responses, don't assume). Open question:
is this a genuine per-device code collision, or did one of the two projects
mis-map it?

## Verification

- `uv run pytest` — unit tests for decoder math (delta-decoding,
  interpolation), pagination/cutoff logic (`fetch_workouts`), and
  `fit_writer` edge cases (range clamping, decimal-string summary fields,
  synthetic records for track-less workouts).
- Live-tested end-to-end against a real Zepp account: 200 workouts (the
  `--limit` default — there's more/older history beyond it, untested)
  across the 14 `TYPE_MAP` sport types above exported cleanly, 0 failures,
  imported successfully into a real Dreeve instance (including
  previously-failing pool swims and other track-less activity types).
