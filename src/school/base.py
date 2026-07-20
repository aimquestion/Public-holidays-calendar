"""Shared plumbing for school-holiday sources.

Every state module exposes a `fetch(years) -> list[HolidayEvent]` that hits the
live source and may raise / return nothing. `resolve()` wraps that call with a
robust fallback chain so a single broken department page never empties the
calendar:

    live fetch  ->  last-known-good cache  ->  manual seed CSV  ->  []

Whenever a live fetch succeeds it overwrites the cache, so the cache is always
the most recent good scrape.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Callable

from .. import config
from ..models import HolidayEvent

_HEADERS = {
    "User-Agent": "aus-holidays-calendar/1.0 (+https://github.com/) meeting-planning",
}


def http_get(url: str, timeout: int = 30) -> bytes:
    """Fetch a URL. Imported lazily so the core build runs without `requests`."""
    import requests

    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.content


# --- cache (last known good) -------------------------------------------------

def _cache_path(state: str) -> Path:
    return Path(config.CACHE_DIR) / f"{state.lower()}.json"


def load_cache(state: str) -> list[HolidayEvent] | None:
    path = _cache_path(state)
    if not path.exists():
        return None
    rows = json.loads(path.read_text())
    return [_from_row(r) for r in rows]


def save_cache(state: str, events: list[HolidayEvent]) -> None:
    path = _cache_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {**asdict(e), "start": e.start.isoformat(), "end": e.end.isoformat()}
        for e in events
    ]
    path.write_text(json.dumps(rows, indent=2, sort_keys=True))


# --- manual seed CSV ---------------------------------------------------------
# Drop data/seed/<state>.csv with columns: summary,start,end  (ISO yyyy-mm-dd)
# to populate a state whose scraper isn't implemented/working yet. This is the
# reliable path for launch day -- paste official dates, get a correct calendar,
# wire up the scraper later.

def load_seed(state: str) -> list[HolidayEvent]:
    path = Path(config.SEED_DIR) / f"{state.lower()}.csv"
    if not path.exists():
        return []
    events: list[HolidayEvent] = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            events.append(
                HolidayEvent(
                    state=state,
                    summary=row.get("summary", "School holidays").strip(),
                    start=date.fromisoformat(row["start"].strip()),
                    end=date.fromisoformat(row["end"].strip()),
                    category="school",
                )
            )
    return events


def breaks_from_terms(
    terms: list[tuple[date, date]], state: str, summary: str = "School holidays"
) -> list[HolidayEvent]:
    """Convert sorted inclusive term (start, end) ranges into the holiday breaks
    that sit BETWEEN them -- which is what matters for meeting planning.

    Give it every term you can scrape across the year range (Term 4 of one year
    followed by Term 1 of the next produces the summer break automatically).
    """
    from datetime import timedelta

    terms = sorted(terms)
    events: list[HolidayEvent] = []
    for (_, end_a), (start_b, _) in zip(terms, terms[1:]):
        gap_start = end_a + timedelta(days=1)
        gap_end = start_b - timedelta(days=1)
        if gap_end >= gap_start:
            events.append(HolidayEvent(state, summary, gap_start, gap_end, "school"))
    return events


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _loose_date(text: str, year: int):
    """Pull the FIRST 'D Month' out of a messy cell (ignores weekday names and
    parentheticals like '(students start ...)'). Returns a date or None."""
    from datetime import date as _date

    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)", text)
    if not m:
        return None
    day = int(m.group(1))
    month = _MONTHS.get(m.group(2).lower())
    if not month:
        return None
    try:
        return _date(year, month, day)
    except ValueError:
        return None


def _table_year(table) -> int | None:
    """Find the 4-digit year a term table belongs to, from its caption or the
    nearest preceding heading/paragraph."""
    cap = table.find("caption")
    if cap:
        m = re.search(r"(20\d\d)", cap.get_text())
        if m:
            return int(m.group(1))
    node = table
    for _ in range(8):
        node = node.find_previous(["h1", "h2", "h3", "h4", "p", "caption", "em", "strong"])
        if node is None:
            break
        m = re.search(r"(20\d\d)", node.get_text())
        if m:
            return int(m.group(1))
    return None


def parse_term_tables(html: bytes, state: str, years: range) -> list[HolidayEvent]:
    """Generic parser for department pages that list term dates in HTML tables
    shaped like: Term | Start date | Finish date, with the year in a nearby
    heading/caption. Terms are collected across every year on the page and turned
    into the holiday breaks between them (summer breaks included automatically).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    terms: list[tuple] = []
    for table in soup.find_all("table"):
        year = _table_year(table)
        if not year:
            continue
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) >= 3 and re.match(r"(?i)\s*term\s*\d", cells[0]):
                start = _loose_date(cells[1], year)
                end = _loose_date(cells[2], year)
                if start and end and end >= start:
                    terms.append((start, end))
    return breaks_from_terms(terms, state)


def find_ics_link(page_html: bytes, base_url: str) -> str | None:
    """Return the first .ics link on a page (used by states that publish a feed
    behind a normal HTML page, e.g. TAS)."""
    from urllib.parse import urljoin

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(page_html, "lxml")
    for a in soup.find_all("a", href=True):
        if a["href"].lower().endswith(".ics"):
            return urljoin(base_url, a["href"])
    return None


def events_from_ics(data: bytes, state: str, years: range) -> list[HolidayEvent]:
    """Parse an upstream .ics feed into HolidayEvents (for states that publish one)."""
    from datetime import datetime, timedelta

    from icalendar import Calendar

    out: list[HolidayEvent] = []
    cal = Calendar.from_ical(data)
    for comp in cal.walk("VEVENT"):
        summary = str(comp.get("summary", "School holidays")).strip()
        dtstart = comp.get("dtstart").dt
        dtend_prop = comp.get("dtend")
        # Normalise to inclusive date range.
        start = dtstart.date() if isinstance(dtstart, datetime) else dtstart
        if dtend_prop is not None:
            dtend = dtend_prop.dt
            end = dtend.date() if isinstance(dtend, datetime) else dtend
            # All-day ICS DTEND is exclusive; step back one day.
            end = end - timedelta(days=1)
            if end < start:
                end = start
        else:
            end = start
        if start.year in years or end.year in years:
            out.append(HolidayEvent(state, summary, start, end, "school"))
    return out


def _from_row(r: dict) -> HolidayEvent:
    return HolidayEvent(
        state=r["state"],
        summary=r["summary"],
        start=date.fromisoformat(r["start"]),
        end=date.fromisoformat(r["end"]),
        category=r["category"],
    )


# --- resolve with fallback ---------------------------------------------------

def resolve(
    state: str,
    fetch: Callable[[range], list[HolidayEvent]],
    years: range,
    status: dict,
) -> list[HolidayEvent]:
    try:
        events = fetch(years)
        if events:
            save_cache(state, events)
            status[state] = {"source": "live", "count": len(events)}
            return events
        raise ValueError("live fetch returned no events")
    except Exception as exc:  # noqa: BLE001 - fail soft on any source error
        cached = load_cache(state)
        if cached:
            status[state] = {"source": "cache", "count": len(cached), "error": str(exc)}
            return cached
        seed = load_seed(state)
        status[state] = {
            "source": "seed" if seed else "none",
            "count": len(seed),
            "error": str(exc),
        }
        return seed
