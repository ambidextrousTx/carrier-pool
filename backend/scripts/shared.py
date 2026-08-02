"""Shared broker -> TMS configuration for the generate/seed scripts. One
place to edit if we ever add a broker, so generate_data.py and
seed_data.py can't drift apart on which parser goes with which broker's
data."""

from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@dataclass(frozen=True)
class BrokerSpec:
    slug: str
    name: str
    tms: str
    seed: int  # only used by generate_data.py


BROKERS: list[BrokerSpec] = [
    BrokerSpec(slug="lone-star-freight", name="Lone Star Freight Partners", tms="freightflow", seed=101),
    BrokerSpec(slug="crossroads-logistics", name="Crossroads Logistics", tms="hauldesk", seed=202),
    BrokerSpec(slug="summit-brokerage", name="Summit Brokerage Group", tms="brokeros", seed=303),
]
