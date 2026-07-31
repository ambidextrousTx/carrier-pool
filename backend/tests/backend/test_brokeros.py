import copy
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from adapters.brokeros import parse_brokeros_sync
from canonical.enums import EquipmentType, LoadStatus, SourceSystem
from tms_fixtures import BROKEROS_SYNC


class TestCoreFields:
    def test_maps_core_fields(self):
        [result] = parse_brokeros_sync(BROKEROS_SYNC)
        load = result.load

        assert load.source_system == SourceSystem.BROKEROS
        assert load.source_native_id == "a0jO900000YgsYJIAZ"
        assert load.source_native_number == "SHP6743062"
        assert load.status == LoadStatus.ACTIVE  # "Ready to Book"
        assert load.source_status_raw == "Ready to Book"
        assert load.equipment_type == EquipmentType.REEFER
        assert load.distance_miles == Decimal("197.4")
        assert load.customer_rate_total_usd == Decimal("1720.00")
        assert load.carrier_rate_total_usd is None  # not booked

    def test_weight_summed_from_line_items(self):
        [result] = parse_brokeros_sync(BROKEROS_SYNC)
        assert result.load.weight_lbs == Decimal("14440.0")

    def test_customer_resolved_via_referenced_records(self):
        [result] = parse_brokeros_sync(BROKEROS_SYNC)
        assert result.customer.source_native_id == "0011I00000NMUrPQAX"
        assert result.customer.name == "Gulf Coast Foods"

    def test_no_carrier_before_booking(self):
        [result] = parse_brokeros_sync(BROKEROS_SYNC)
        assert result.carrier is None
        assert result.load.carrier_source_native_id is None

    def test_timestamps_already_utc(self):
        [result] = parse_brokeros_sync(BROKEROS_SYNC)
        assert result.load.source_created_at == datetime(2026, 7, 6, 9, 40, 2, tzinfo=timezone.utc)


class TestStops:
    def test_stops_resolved_via_referenced_records(self):
        [result] = parse_brokeros_sync(BROKEROS_SYNC)
        pickup, dropoff = result.load.stops

        assert pickup.sequence == 1
        assert pickup.is_pickup and not pickup.is_dropoff
        assert pickup.city == "Sugar Land"
        assert pickup.state == "TX"
        assert pickup.zip_code == "77478"
        assert pickup.scheduled_date == date(2026, 7, 7)
        assert pickup.actual_arrival_at is None

        assert dropoff.sequence == 2
        assert dropoff.is_dropoff and not dropoff.is_pickup
        assert dropoff.city == "Schertz"

    def test_more_than_two_stops_sorted_by_number_regardless_of_array_order(self):
        raw = copy.deepcopy(BROKEROS_SYNC)
        referenced = raw["referenced_records"]
        referenced["LOC_MIDDLE"] = {
            "type": "Location",
            "Name": "Waco Cross-dock",
            "bos__City__c": "Waco",
            "bos__State__c": "TX",
            "bos__Postal_Code__c": "76701",
        }
        middle_stop = {
            "bos__Number__c": 2.0,
            "bos__Is_Pickup__c": False,
            "bos__Is_Dropoff__c": False,
            "bos__Location__c": "LOC_MIDDLE",
            "bos__Scheduled_Date__c": "2026-07-07",
            "bos__Arrival_Time__c": None,
        }
        # Renumber the original dropoff to 3, then deliberately scramble
        # array order to prove we sort by bos__Number__c, not array position.
        raw["records"][0]["bos__Stops__r"][1]["bos__Number__c"] = 3.0
        raw["records"][0]["bos__Stops__r"] = [
            raw["records"][0]["bos__Stops__r"][1],  # dropoff (3.0) first in array
            middle_stop,  # (2.0) second in array
            raw["records"][0]["bos__Stops__r"][0],  # pickup (1.0) last in array
        ]

        [result] = parse_brokeros_sync(raw)
        stops = result.load.stops
        assert [s.sequence for s in stops] == [1, 2, 3]
        assert stops[0].city == "Sugar Land"  # pickup
        assert stops[1].city == "Waco"  # middle
        assert stops[1].is_pickup is False and stops[1].is_dropoff is False
        assert stops[2].city == "Schertz"  # dropoff

    def test_missing_referenced_record_raises(self):
        raw = copy.deepcopy(BROKEROS_SYNC)
        raw["records"][0]["bos__Stops__r"][0]["bos__Location__c"] = "DOES_NOT_EXIST"
        with pytest.raises(ValueError, match="referenced_records missing entry"):
            parse_brokeros_sync(raw)


class TestWeightUnits:
    def test_mixed_units_converted_before_summing(self):
        raw = copy.deepcopy(BROKEROS_SYNC)
        raw["records"][0]["bos__Line_Items__r"] = [
            {
                "bos__Commodity__c": "Packaged foods",
                "bos__Weight__c": 10000.0,
                "bos__Weight_Units__c": "lbs",
                "bos__Pallet_Count__c": 12.0,
            },
            {
                "bos__Commodity__c": "Canned goods",
                "bos__Weight__c": 1000.0,
                "bos__Weight_Units__c": "kg",
                "bos__Pallet_Count__c": 6.0,
            },
        ]
        [result] = parse_brokeros_sync(raw)
        # 10000 lbs + (1000 kg -> 2204.6 lbs) = 12204.6
        assert result.load.weight_lbs == Decimal("12204.6")

    def test_missing_weight_units_defaults_to_lbs(self):
        raw = copy.deepcopy(BROKEROS_SYNC)
        del raw["records"][0]["bos__Line_Items__r"][0]["bos__Weight_Units__c"]
        [result] = parse_brokeros_sync(raw)
        assert result.load.weight_lbs == Decimal("14440.0")

    def test_unrecognized_weight_unit_raises(self):
        raw = copy.deepcopy(BROKEROS_SYNC)
        raw["records"][0]["bos__Line_Items__r"][0]["bos__Weight_Units__c"] = "tonnes"
        with pytest.raises(ValueError, match="unrecognized bos__Weight_Units__c"):
            parse_brokeros_sync(raw)


class TestCarrierBooked:
    def test_carrier_resolved_with_assumed_mc_dot_fields(self):
        raw = copy.deepcopy(BROKEROS_SYNC)
        raw["referenced_records"]["ACCT_CARRIER_1"] = {
            "type": "Account",
            "record_type": "Carrier",
            "Name": "RIO GRANDE HAULING LLC",
            "bos__MC_Number__c": "998877",
            "bos__DOT_Number__c": "554433",
            "bos__Phone__c": "+15125550199",
            "bos__City__c": "Laredo",
            "bos__State__c": "TX",
        }
        raw["records"][0]["bos__Carrier__c"] = "ACCT_CARRIER_1"
        raw["records"][0]["bos__Load_Status__c"] = "Booked"

        [result] = parse_brokeros_sync(raw)
        carrier = result.carrier
        assert carrier is not None
        assert carrier.name == "RIO GRANDE HAULING LLC"
        assert carrier.mc_number == "998877"
        assert carrier.dot_number == "554433"
        assert result.load.carrier_source_native_id == "ACCT_CARRIER_1"
        assert result.load.status == LoadStatus.COVERED


class TestStatusMapping:
    @pytest.mark.parametrize(
        "raw_status,expected",
        [
            ("Quotes Requested", LoadStatus.PLANNED),
            ("Ready to Book", LoadStatus.ACTIVE),
            ("Booked", LoadStatus.COVERED),
            ("In Transit", LoadStatus.IN_TRANSIT),
            ("Delivered", LoadStatus.DELIVERED),
            ("Invoiced", LoadStatus.DELIVERED),
            ("Paid", LoadStatus.COMPLETED),
        ],
    )
    def test_every_known_status_maps(self, raw_status, expected):
        raw = copy.deepcopy(BROKEROS_SYNC)
        raw["records"][0]["bos__Load_Status__c"] = raw_status
        [result] = parse_brokeros_sync(raw)
        assert result.load.status == expected

    def test_unrecognized_status_raises(self):
        raw = copy.deepcopy(BROKEROS_SYNC)
        raw["records"][0]["bos__Load_Status__c"] = "Ghost Status"
        with pytest.raises(ValueError, match="unrecognized bos__Load_Status__c"):
            parse_brokeros_sync(raw)


class TestEquipmentMapping:
    @pytest.mark.parametrize(
        "raw_equipment,expected",
        [
            ("Dry Van", EquipmentType.DRY_VAN),
            ("Reefer", EquipmentType.REEFER),
            ("Flatbed", EquipmentType.FLATBED),
            (None, EquipmentType.UNKNOWN),  # explicitly NOT Dry Van -- see source's own warning
            ("Something Else", EquipmentType.UNKNOWN),
        ],
    )
    def test_equipment_parsing(self, raw_equipment, expected):
        raw = copy.deepcopy(BROKEROS_SYNC)
        raw["records"][0]["bos__Equipment_Type__c"] = raw_equipment
        [result] = parse_brokeros_sync(raw)
        assert result.load.equipment_type == expected
