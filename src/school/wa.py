"""Western Australia school holidays — parsed from official term-date tables.

Source: https://www.education.wa.edu.au/future-term-dates
WA publishes term dates as HTML tables; base.parse_term_tables reads them
and derives the between-term holiday breaks. Verified 2026 dates are seeded in
data/seed/wa.csv as the safety net, and the live scrape extends/refreshes
this on GitHub Actions.
"""

from ..models import HolidayEvent
from . import base

SOURCE_URL = "https://www.education.wa.edu.au/future-term-dates"


def fetch(years: range) -> list[HolidayEvent]:
    return base.parse_term_tables(base.http_get(SOURCE_URL), "WA", years)
