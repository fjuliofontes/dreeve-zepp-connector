"""CLI entrypoint: fetch new Zepp workouts and write them as .FIT files."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from . import decoder, fit_writer
from .config import Config, ConfigError
from .ledger import Ledger
from .zepp_client import ZeppDataClient


def parse_since(since: str | None) -> datetime | None:
    """`since` is None (no lower bound), "all", "-Nd" (N days back), or an
    ISO date (YYYY-MM-DD)."""
    if not since or since == "all":
        return None
    if since.startswith("-") and since.endswith("d"):
        days = int(since[1:-1])
        return datetime.now(tz=timezone.utc) - timedelta(days=days)
    return datetime.fromisoformat(since).replace(tzinfo=timezone.utc)


def _filename_for(summary: dict, start_time: datetime) -> str:
    trackid = summary["trackid"]
    zepp_type = summary.get("type", "unknown")
    return f"{start_time.strftime('%Y-%m-%dT%H-%M-%SZ')}_{trackid}_{zepp_type}.fit"


def fetch_workouts(
    client: ZeppDataClient, cutoff: datetime | None, limit: int, page_size: int = 100
) -> list[dict]:
    """Page back through workout history (newest-first) until `limit`
    workouts are collected or a page's oldest workout is already older than
    `cutoff` — whichever comes first. Zepp's history endpoint pages via a
    `trackid` cursor, not an offset, so a single capped call can't reliably
    reach an arbitrary `--since` date; this walks back as many pages as
    needed.
    """
    collected: list[dict] = []
    cursor: int | str | None = None
    while len(collected) < limit:
        items, cursor = client.workouts_page(
            limit=min(page_size, limit - len(collected)), before_trackid=cursor
        )
        if not items:
            break
        collected.extend(items)

        trackids = [int(w["trackid"]) for w in items if w.get("trackid")]
        oldest = min(trackids) if trackids else None
        if cutoff and oldest is not None and datetime.fromtimestamp(oldest, tz=timezone.utc) < cutoff:
            break
        if cursor is None:
            break
    return collected[:limit]


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        help='ISO date (e.g. 2026-07-24), "-Nd" offset (e.g. -30d), or "all" (default: no lower bound — '
        "everything up to --limit)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="max workouts to fetch in total, paging back through history as needed (default 200)",
    )
    parser.add_argument("--output-dir", help="folder to write .FIT files into (Dreeve's watch folder)")
    parser.add_argument("--dry-run", action="store_true", help="list what would be exported, write nothing")
    args = parser.parse_args()

    try:
        cfg = Config.from_env(since_override=args.since, output_dir_override=args.output_dir)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    cutoff = parse_since(cfg.since)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(cfg.ledger_path)

    client = ZeppDataClient(email=cfg.email, password=cfg.password, country=cfg.country)
    cached_auth = ledger.cached_auth()
    if cached_auth and cached_auth.get("email") == cfg.email and cached_auth.get("country") == cfg.country:
        client.use_cached_auth(cached_auth["app_token"], cached_auth["user_id"])
    else:
        try:
            client.login()
        except Exception as e:
            print(f"login failed: {e}", file=sys.stderr)
            return 1

    try:
        workouts = fetch_workouts(client, cutoff, limit=args.limit)
    except Exception as e:
        # Most likely a stale cached token whose re-login (see
        # ZeppDataClient._get) also failed - e.g. changed password.
        print(f"failed to fetch workout history: {e}", file=sys.stderr)
        return 1

    exported = skipped = failed = 0
    for summary in workouts:
        trackid = summary.get("trackid")
        if not trackid:
            continue
        trackid = str(trackid)
        start_time = datetime.fromtimestamp(int(trackid), tz=timezone.utc)

        if ledger.has(trackid):
            skipped += 1
            continue
        if cutoff and start_time < cutoff:
            continue

        filename = _filename_for(summary, start_time)
        if args.dry_run:
            print(f"(dry-run) would export {filename}")
            exported += 1
            continue

        try:
            detail = client.workout_detail(trackid, source=summary.get("source"))
            points = decoder.parse_points(int(trackid), detail)
            splits = decoder.parse_kilometer_splits(detail)
            output_path = cfg.output_dir / filename
            device_id = summary.get("devicesource")
            device_name = cfg.device_names.get(str(device_id)) if device_id is not None else None
            fit_writer.write_fit(summary, points, output_path, splits=splits, device_name=device_name)
            ledger.mark(trackid, filename, datetime.now(tz=timezone.utc).isoformat())
            print(f"exported {filename} ({len(points)} track points)")
            exported += 1
        except Exception as e:
            print(f"failed to export workout {trackid}: {e}", file=sys.stderr)
            failed += 1

    if not args.dry_run:
        if client.app_token and client.user_id:
            ledger.set_auth(client.app_token, client.user_id, cfg.country, cfg.email)
        ledger.save()

    print(f"done: {exported} exported, {skipped} already synced, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
