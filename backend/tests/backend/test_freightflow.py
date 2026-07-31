import copy
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from adapters.freightflow import parse_freightflow_sync
from canonical.enums import EquipmentType, LoadStatus, SourceSystem
from tms_fixtures import FREIGHTFLOW_SYNC_BOOKED, FREIGHTFLOW_SYNC_UNBOOKED


class TestUnbookedLoad:
    def test_maps_core_fields(self):
        [result] = parse_freightflow_sync(FREIGHTFLOW_SYNC_UNBOOKED)
        load = result.load

        assert load.source_system == SourceSystem.FREIGHTFLOW
        assert load.source_native_id == "127472397"
        assert load.status == LoadStatus.ACTIVE  # "Booking"
        assert load.source_status_raw == "Booking"
        assert load.equipment_type == EquipmentType.DRY_VAN
        assert load.distance_miles == Decimal("242.1")
        assert load.weight_lbs == Decimal("24000.0")
        assert load.customer_rate_total_usd == Decimal("1450.0")
        assert load.carrier_rate_total_usd is None  # not booked yet

    def test_no_carrier_before_booking(self):
        [result] = parse_freightflow_sync(FREIGHTFLOW_SYNC_UNBOOKED)
        assert result.carrier is None
        assert result.load.carrier_source_native_id is None

    def test_customer(self):
        [result] = parse_freightflow_sync(FREIGHTFLOW_SYNC_UNBOOKED)
        assert result.customer.source_native_id == "889264"
        assert result.customer.name == "Lone Star Beverages"
        assert result.load.customer_source_native_id == "889264"

    def test_stops(self):
        [result] = parse_freightflow_sync(FREIGHTFLOW_SYNC_UNBOOKED)
        stops = result.load.stops
        assert len(stops) == 2

        pickup, delivery = stops
        assert pickup.sequence == 1
        assert pickup.is_pickup is True
        assert pickup.is_dropoff is False
        assert pickup.city == "GRAND PRAIRIE"
        assert pickup.state == "TX"
        assert pickup.zip_code == "75050"
        assert pickup.scheduled_date == pickup.scheduled_window_start.date()
        assert pickup.scheduled_window_start == datetime(2026, 7, 7, 13, 0, 0, tzinfo=timezone.utc)
        assert pickup.actual_departure_at is None

        assert delivery.sequence == 2
        assert delivery.is_pickup is False
        assert delivery.is_dropoff is True
        assert delivery.city == "KATY"

    def test_timestamps_normalized_to_utc(self):
        [result] = parse_freightflow_sync(FREIGHTFLOW_SYNC_UNBOOKED)
        load = result.load
        assert load.source_created_at == datetime(2026, 7, 6, 9, 12, 44, tzinfo=timezone.utc)
        assert load.source_last_modified_at == datetime(2026, 7, 6, 9, 12, 44, tzinfo=timezone.utc)


class TestBookedLoad:
    def test_status_moves_to_covered(self):
        [result] = parse_freightflow_sync(FREIGHTFLOW_SYNC_BOOKED)
        assert result.load.status == LoadStatus.COVERED  # "Dispatched"
        assert result.load.source_status_raw == "Dispatched"

    def test_carrier_rate_now_set(self):
        [result] = parse_freightflow_sync(FREIGHTFLOW_SYNC_BOOKED)
        assert result.load.carrier_rate_total_usd == Decimal("1180.0")

    def test_carrier_populated_with_mc_dot(self):
        [result] = parse_freightflow_sync(FREIGHTFLOW_SYNC_BOOKED)
        carrier = result.carrier
        assert carrier is not None
        assert carrier.source_system == SourceSystem.FREIGHTFLOW
        assert carrier.source_native_id == "835692"
        assert carrier.name == "IBRAHIM TRANSPORT INC"
        assert carrier.mc_number == "1346382"
        assert carrier.dot_number == "3771394"
        assert carrier.phone == "+15714906959"
        assert result.load.carrier_source_native_id == "835692"

    def test_lastmodified_advances_but_created_does_not(self):
        [unbooked] = parse_freightflow_sync(FREIGHTFLOW_SYNC_UNBOOKED)
        [booked] = parse_freightflow_sync(FREIGHTFLOW_SYNC_BOOKED)
        assert booked.load.source_created_at == unbooked.load.source_created_at
        assert booked.load.source_last_modified_at > unbooked.load.source_last_modified_at


class TestStatusMapping:
    @pytest.mark.parametrize(
        "raw_status,expected",
        [
            ("Quoting", LoadStatus.PLANNED),
            ("Booking", LoadStatus.ACTIVE),
            ("Dispatched", LoadStatus.COVERED),
            ("At Shipper", LoadStatus.COVERED),
            ("En Route", LoadStatus.IN_TRANSIT),
            ("At Receiver", LoadStatus.IN_TRANSIT),
            ("Delivered", LoadStatus.DELIVERED),
            ("Completed", LoadStatus.COMPLETED),
        ],
    )
    def test_every_known_status_maps(self, raw_status, expected):
        raw = copy.deepcopy(FREIGHTFLOW_SYNC_UNBOOKED)
        raw["loads"][0]["status"] = raw_status
        [result] = parse_freightflow_sync(raw)
        assert result.load.status == expected

    def test_unrecognized_status_raises(self):
        raw = copy.deepcopy(FREIGHTFLOW_SYNC_UNBOOKED)
        raw["loads"][0]["status"] = "Some New Status FreightFlow Invented"
        with pytest.raises(ValueError, match="unrecognized status"):
            parse_freightflow_sync(raw)


class TestEquipmentMapping:
    @pytest.mark.parametrize(
        "raw_equipment,expected",
        [
            ("53 ft Van | Dry", EquipmentType.DRY_VAN),
            ("53 ft Van | Reefer", EquipmentType.REEFER),
            ("48 ft Flatbed", EquipmentType.FLATBED),
            (None, EquipmentType.UNKNOWN),
            ("Something Unrecognized", EquipmentType.UNKNOWN),
        ],
    )
    def test_equipment_parsing(self, raw_equipment, expected):
        raw = copy.deepcopy(FREIGHTFLOW_SYNC_UNBOOKED)
        raw["loads"][0]["equipment"] = raw_equipment
        [result] = parse_freightflow_sync(raw)
        assert result.load.equipment_type == expected


class TestMultiStop:
    def test_middle_stops_are_neither_pickup_nor_dropoff(self):
        raw = copy.deepcopy(FREIGHTFLOW_SYNC_UNBOOKED)
        middle_stop = copy.deepcopy(raw["loads"][0]["stops"][0])
        middle_stop["city"] = "WACO"
        raw["loads"][0]["stops"].insert(1, middle_stop)

        [result] = parse_freightflow_sync(raw)
        stops = result.load.stops
        assert len(stops) == 3
        assert stops[0].is_pickup and not stops[0].is_dropoff
        assert not stops[1].is_pickup and not stops[1].is_dropoff
        assert stops[2].is_dropoff and not stops[2].is_pickup
