"""
Small, isolated date/time helpers for "is this event scheduled for
today" filtering across the four Kenyan prematch feeds.

Each bookmaker reports start times in a different shape (ISO-ish
strings, unix seconds, etc); the individual parsers are responsible
for converting to a timezone-aware-in-spirit `datetime` first (plain
naive datetime, treated as Kenya local time -- see
kenyan/config.py::KENYA_UTC_OFFSET_HOURS), then this module answers the
single "today, in Kenya" question consistently.
"""
from datetime import datetime, timedelta, timezone

from kenyan.config import KENYA_UTC_OFFSET_HOURS

KENYA_TZ = timezone(timedelta(hours=KENYA_UTC_OFFSET_HOURS))


def now_kenya() -> datetime:
    return datetime.now(tz=KENYA_TZ)


def to_kenya_time(dt: datetime) -> datetime:
    """
    Normalizes `dt` to Kenya local time. A naive `dt` (no tzinfo) is
    assumed to already represent UTC, matching how each parser
    constructs its datetimes from unix timestamps / ISO-8601 "Z"-less
    strings observed live from these bookmakers.
    """

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(KENYA_TZ)


def is_today_in_kenya(dt: datetime, *, reference: datetime = None) -> bool:
    """
    True if `dt` falls on the same Kenya-local calendar date as
    `reference` (defaults to "now, in Kenya").
    """

    reference = reference or now_kenya()
    local_dt = to_kenya_time(dt)
    local_reference = to_kenya_time(reference) if reference.tzinfo else reference.replace(
        tzinfo=KENYA_TZ
    )
    return local_dt.date() == local_reference.date()


def unix_seconds_to_datetime(seconds) -> datetime:
    return datetime.fromtimestamp(float(seconds), tz=timezone.utc)
