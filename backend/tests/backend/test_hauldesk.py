import copy
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from adapters.hauldesk import parse_hauldesk_sync
from canonical.enums import EquipmentType, LoadStatus, RateSide, SourceSystem
from tests.tms_fixtures import HAULDESK_SYNC


class TestCoreFields:
    def test_maps_core_fields_and_converts_units(self):
        [result] = parse_hauldesk_sync(HAULDESK_SYNC)
        load = result.load

        assert load.source_system == SourceSystem.HAULDESK
        assert load.source_native_id == "HD-2026-004417"
        assert load.status == LoadStatus.COVERED  # status_code 30
        assert load.source_status_raw == "30"
        assert load.equipment_type == EquipmentType.DRY_VAN  # "V"
        assert load.distance_miles == Decimal("242.1")  # converted from 389.6 km
        assert load.weight_lbs == Decimal("24000.0")  # converted from 10886.2 kg

    def test_no_single_authoritative_total(self):
        # HaulDesk's money is line items, not a total field -- this
        # adapter deliberately leaves both totals None (see Load docstring)
        [result] = parse_hauldesk_sync(HAULDESK_SYNC)
        assert result.load.customer_rate_total_usd is None
        assert result.load.carrier_rate_total_usd is None

    def test_customer(self):
        [result] = parse_hauldesk_sync(HAULDESK_SYNC)
        assert result.customer.source_native_id == "C-0031"
        assert result.customer.name == "Alamo Building Supply"

    def test_timestamps_localized_from_naive_central_to_utc(self):
        [result] = parse_hauldesk_sync(HAULDESK_SYNC)
        load = result.load
        assert load.source_created_at == datetime(2026, 7, 5, 19, 22, 10, tzinfo=timezone.utc)
        assert load.source_last_modified_at == datetime(2026, 7, 6, 8, 45, 33, tzinfo=timezone.utc)


class TestStops:
    def test_pickup_and_delivery_flattened_into_two_stops(self):
        [result] = parse_hauldesk_sync(HAULDESK_SYNC)
        pickup, delivery = result.load.stops

        assert pickup.sequence == 1
        assert pickup.is_pickup and not pickup.is_dropoff
        assert pickup.city == "New Braunfels"
        assert pickup.state == "TX"
        assert pickup.zip_code == "78130"
        assert pickup.scheduled_date == date(2026, 7, 7)
        assert pickup.scheduled_window_start is None  # HaulDesk gives date only, no window
        assert pickup.actual_departure_at is None

        assert delivery.sequence == 2
        assert delivery.is_dropoff and not delivery.is_pickup
        assert delivery.city == "Pasadena"
        assert delivery.scheduled_date == date(2026, 7, 8)
        assert delivery.actual_arrival_at is None

    def test_actual_departure_and_arrival_populate_when_present(self):
        raw = copy.deepcopy(HAULDESK_SYNC)
        raw["loads"][0]["pu_departed_at"] = "2026-07-07 09:15:00"
        raw["loads"][0]["del_arrived_at"] = "2026-07-08 10:05:00"

        [result] = parse_hauldesk_sync(raw)
        pickup, delivery = result.load.stops
        assert pickup.actual_departure_at == datetime(2026, 7, 7, 14, 15, 0, tzinfo=timezone.utc)
        assert delivery.actual_arrival_at == datetime(2026, 7, 8, 15, 5, 0, tzinfo=timezone.utc)
        # asymmetric by design -- HaulDesk never gives departure-from-delivery
        # or arrival-at-pickup
        assert pickup.actual_arrival_at is None
        assert delivery.actual_departure_at is None


class TestCarrierJoin:
    def test_carrier_present_in_same_file(self):
        [result] = parse_hauldesk_sync(HAULDESK_SYNC)
        carrier = result.carrier
        assert carrier is not None
        assert carrier.source_native_id == "66861"
        assert carrier.name == "DELTA PRIME LLC"
        assert carrier.mc_number == "884201"
        assert carrier.dot_number == "2551377"
        assert carrier.home_city == "Seguin"
        assert carrier.home_state == "TX"
        assert result.load.carrier_source_native_id == "66861"

    def test_no_carrier_before_booking(self):
        raw = copy.deepcopy(HAULDESK_SYNC)
        raw["loads"][0]["carrier_ref"] = None
        raw["loads"][0]["status_code"] = 20
        raw["carriers"] = []

        [result] = parse_hauldesk_sync(raw)
        assert result.carrier is None
        assert result.load.carrier_source_native_id is None

    def test_carrier_referenced_but_not_redefined_in_this_file(self):
        # Realistic scenario per HaulDesk's own documentation: a carrier
        # was booked in an earlier sync and hasn't changed since, so this
        # file's "carriers" array doesn't repeat it. The relationship
        # must still come through even though we can't resolve details.
        raw = copy.deepcopy(HAULDESK_SYNC)
        raw["carriers"] = []  # carrier_ref 66861 now resolves to nothing in THIS file

        [result] = parse_hauldesk_sync(raw)
        assert result.carrier is None
        assert result.load.carrier_source_native_id == "66861"


class TestRateLineItems:
    def test_line_items_parsed_and_sides_mapped(self):
        [result] = parse_hauldesk_sync(HAULDESK_SYNC)
        items = result.load.rate_line_items
        assert len(items) == 2

        pay_item = next(i for i in items if i.side == RateSide.PAY)
        bill_item = next(i for i in items if i.side == RateSide.BILL)
        assert pay_item.source_native_id == "910233"
        assert pay_item.code == "LINEHAUL"
        assert pay_item.amount_usd == Decimal("1035.00")
        assert bill_item.amount_usd == Decimal("1310.00")

    def test_load_with_no_rate_rows_in_this_file_gets_empty_list(self):
        raw = copy.deepcopy(HAULDESK_SYNC)
        raw["rates"] = []
        [result] = parse_hauldesk_sync(raw)
        assert result.load.rate_line_items == []

    def test_negative_correction_row(self):
        raw = copy.deepcopy(HAULDESK_SYNC)
        raw["rates"].append(
            {
                "rate_id": 910299,
                "load_num": "HD-2026-004417",
                "side": "pay",
                "code": "ADJUSTMENT",
                "amount_usd": -75.00,
                "created_at": "2026-07-06 09:00:00",
            }
        )
        [result] = parse_hauldesk_sync(raw)
        adjustment = next(i for i in result.load.rate_line_items if i.code == "ADJUSTMENT")
        assert adjustment.amount_usd == Decimal("-75.00")

    def test_unrecognized_rate_side_raises(self):
        raw = copy.deepcopy(HAULDESK_SYNC)
        raw["rates"][0]["side"] = "escrow"
        with pytest.raises(ValueError, match="unrecognized rate side"):
            parse_hauldesk_sync(raw)


class TestStatusMapping:
    @pytest.mark.parametrize(
        "code,expected",
        [
            (10, LoadStatus.PLANNED),
            (20, LoadStatus.ACTIVE),
            (30, LoadStatus.COVERED),
            (40, LoadStatus.IN_TRANSIT),
            (50, LoadStatus.DELIVERED),
            (90, LoadStatus.COMPLETED),
        ],
    )
    def test_every_known_status_maps(self, code, expected):
        raw = copy.deepcopy(HAULDESK_SYNC)
        raw["loads"][0]["status_code"] = code
        [result] = parse_hauldesk_sync(raw)
        assert result.load.status == expected

    def test_unrecognized_status_raises(self):
        raw = copy.deepcopy(HAULDESK_SYNC)
        raw["loads"][0]["status_code"] = 999
        with pytest.raises(ValueError, match="unrecognized status_code"):
            parse_hauldesk_sync(raw)


class TestEquipmentMapping:
    @pytest.mark.parametrize(
        "code,expected",
        [
            ("V", EquipmentType.DRY_VAN),
            ("R", EquipmentType.REEFER),
            ("F", EquipmentType.FLATBED),
            (None, EquipmentType.UNKNOWN),
            ("X", EquipmentType.UNKNOWN),
        ],
    )
    def test_equipment_parsing(self, code, expected):
        raw = copy.deepcopy(HAULDESK_SYNC)
        raw["loads"][0]["equip"] = code
        [result] = parse_hauldesk_sync(raw)
        assert result.load.equipment_type == expected
