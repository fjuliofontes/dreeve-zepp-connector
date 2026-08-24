from datetime import datetime, timezone

from dreeve_zepp_connector.main import fetch_workouts

DAY = 86400


class StubClient:
    """Fakes ZeppDataClient.workouts_page() over a fixed set of pages,
    newest-first, cursor-linked like the real trackid-based pagination."""

    def __init__(self, pages: list[list[dict]]):
        self.pages = pages
        self.calls: list[int | None] = []

    def workouts_page(self, limit: int, before_trackid=None):
        self.calls.append(before_trackid)
        index = 0 if before_trackid is None else before_trackid
        if index >= len(self.pages):
            return [], None
        items = self.pages[index][:limit]
        next_cursor = index + 1 if index + 1 < len(self.pages) else None
        return items, next_cursor


def _workout(trackid: int) -> dict:
    return {"trackid": str(trackid), "type": 1}


def test_stops_at_limit_without_fetching_extra_pages():
    now = int(datetime.now(tz=timezone.utc).timestamp())
    pages = [[_workout(now - i * DAY) for i in range(3)], [_workout(now - i * DAY) for i in range(3, 6)]]
    client = StubClient(pages)

    result = fetch_workouts(client, cutoff=None, limit=3, page_size=3)

    assert len(result) == 3
    assert client.calls == [None]


def test_pages_back_until_cutoff_is_covered():
    now = int(datetime.now(tz=timezone.utc).timestamp())
    # 6 workouts, one per day, spread across two pages of 3.
    pages = [[_workout(now - i * DAY) for i in range(3)], [_workout(now - i * DAY) for i in range(3, 6)]]
    client = StubClient(pages)
    cutoff = datetime.fromtimestamp(now - 4 * DAY, tz=timezone.utc)

    result = fetch_workouts(client, cutoff=cutoff, limit=200, page_size=3)

    # Needs both pages: page 1's oldest item (day 2) is still newer than the
    # day-4 cutoff, so it must keep paging into page 2.
    assert len(result) == 6
    assert client.calls == [None, 1]


def test_stops_paging_once_a_page_is_entirely_before_cutoff():
    now = int(datetime.now(tz=timezone.utc).timestamp())
    pages = [
        [_workout(now - i * DAY) for i in range(3)],
        [_workout(now - i * DAY) for i in range(3, 6)],
        [_workout(now - i * DAY) for i in range(6, 9)],
    ]
    client = StubClient(pages)
    cutoff = datetime.fromtimestamp(now - 4 * DAY, tz=timezone.utc)

    fetch_workouts(client, cutoff=cutoff, limit=200, page_size=3)

    # Page 2 (days 3-5) already dips below the day-4 cutoff, so page 3 is
    # never fetched.
    assert client.calls == [None, 1]


def test_empty_page_stops_pagination():
    client = StubClient([])

    result = fetch_workouts(client, cutoff=None, limit=200, page_size=50)

    assert result == []
    assert client.calls == [None]
