from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

_CENTRAL = ZoneInfo("America/Chicago")


def parse_offset_aware_iso(value: str) -> datetime:
    """FreightFlow and BrokerOS both give ISO-8601 timestamps with an
    explicit offset already. Normalize to UTC."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"expected an offset-aware ISO timestamp, got a naive value: {value!r}")
    return dt.astimezone(timezone.utc)


def parse_naive_central(value: str) -> datetime:
    """HaulDesk gives naive 'YYYY-MM-DD HH:MM:SS' strings, documented as
    US Central time with no offset. Localized using real IANA DST rules
    for America/Chicago, not a fixed UTC-5/UTC-6 offset.

    Two edge cases, both deliberate, both verified empirically rather than
    assumed (see backend/tests/adapters/test_timeutils.py):

    - The one hour each fall when local time is ambiguous (ran twice):
      resolves to the EARLIER instant (fold=0, still-daylight-time) --
      Python's default for a naive datetime, so this needs no special code,
      just needs to not be overridden.
    - The one hour each spring that doesn't exist at all (clocks skip it):
      does not raise. zoneinfo silently extrapolates using the
      pre-transition offset. We accept this default rather than adding
      detection/rejection logic for an edge case unlikely to ever land on
      a real pickup/delivery window.
    """
    naive = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    localized = naive.replace(tzinfo=_CENTRAL)
    return localized.astimezone(timezone.utc)


def parse_date_only(value: str) -> date:
    return date.fromisoformat(value)
