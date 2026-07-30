from datetime import date, datetime, timezone

import pytest

from adapters.timeutils import (
    parse_date_only,
    parse_naive_central,
    parse_offset_aware_iso,
)


class TestParseOffsetAwareIso:
    def test_freightflow_style_offset(self):
        # FreightFlow: "-05:00" style offset
        assert parse_offset_aware_iso("2026-07-06T04:12:44-05:00") == datetime(
            2026, 7, 6, 9, 12, 44, tzinfo=timezone.utc
        )

    def test_brokeros_style_utc_offset(self):
        # BrokerOS: ".000+0000" style -- no colon in the offset, explicit
        # milliseconds. Python 3.11+'s fromisoformat handles both.
        assert parse_offset_aware_iso("2026-07-06T09:40:02.000+0000") == datetime(
            2026, 7, 6, 9, 40, 2, tzinfo=timezone.utc
        )

    def test_rejects_naive_input(self):
        # A naive string here would silently mean "we don't actually know
        # the offset" -- that must fail loudly, not guess.
        with pytest.raises(ValueError, match="naive"):
            parse_offset_aware_iso("2026-07-06T04:12:44")


class TestParseNaiveCentral:
    def test_ordinary_central_daylight_time(self):
        # Early July -> CDT (UTC-5)
        assert parse_naive_central("2026-07-06 03:45:33") == datetime(
            2026, 7, 6, 8, 45, 33, tzinfo=timezone.utc
        )

    def test_ordinary_central_standard_time(self):
        # Mid-January -> CST (UTC-6)
        assert parse_naive_central("2026-01-15 09:00:00") == datetime(
            2026, 1, 15, 15, 0, 0, tzinfo=timezone.utc
        )

    def test_fall_back_ambiguous_hour_resolves_to_earlier_instant(self):
        # 2026-11-01 01:00-01:59 local occurs twice (DST ends at 2 AM
        # local, clocks fall back to 1 AM). Policy: resolve to the
        # earlier, still-daylight-time (CDT, UTC-5) instant.
        assert parse_naive_central("2026-11-01 01:30:00") == datetime(
            2026, 11, 1, 6, 30, 0, tzinfo=timezone.utc
        )

    def test_spring_forward_gap_hour_does_not_raise(self):
        # 2026-03-08 02:00-02:59 local doesn't exist (clocks jump from
        # 1:59:59 to 3:00:00). We don't detect/reject this -- zoneinfo
        # extrapolates using the pre-transition (CST, UTC-6) offset, which
        # is what this test pins down as the accepted behavior.
        assert parse_naive_central("2026-03-08 02:30:00") == datetime(
            2026, 3, 8, 8, 30, 0, tzinfo=timezone.utc
        )


class TestParseDateOnly:
    def test_parses_iso_date(self):
        assert parse_date_only("2026-07-07") == date(2026, 7, 7)
