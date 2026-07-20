"""Australian Capital Territory school holidays — parsed from official term-date tables.

Source: https://www.education.act.gov.au/public-school-life/term_dates_and_public_holidays
ACT publishes term dates as HTML tables; base.parse_term_tables reads them
and derives the between-term holiday breaks. Verified 2026 dates are seeded in
data/seed/act.csv as the safety net, and the live scrape extends/refreshes
this on GitHub Actions.
"""

from ..models import HolidayEvent
from . import base

SOURCE_URL = "https://www.education.act.gov.au/public-school-life/term_dates_and_public_holidays"


def fetch(years: range) -> list[HolidayEvent]:
    return base.parse_term_tables(base.http_get(SOURCE_URL), "ACT", years)
