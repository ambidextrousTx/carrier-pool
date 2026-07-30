from enum import Enum


class SourceSystem(str, Enum):
    """Which broker TMS a record originated from."""

    FREIGHTFLOW = "FREIGHTFLOW"
    HAULDESK = "HAULDESK"
    BROKEROS = "BROKEROS"


class LoadStatus(str, Enum):
    """Our six-status vocabulary. Every source's native status maps into
    exactly one of these -- see each adapter's status map for the mapping,
    and Load.source_status_raw for the original value we mapped from."""

    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COVERED = "COVERED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"


class EquipmentType(str, Enum):
    DRY_VAN = "DRY_VAN"
    REEFER = "REEFER"
    FLATBED = "FLATBED"
    UNKNOWN = "UNKNOWN"


class RateSide(str, Enum):
    """Which side of the transaction a rate line item belongs to."""

    BILL = "BILL"  # customer -> broker
    PAY = "PAY"  # broker -> carrier
