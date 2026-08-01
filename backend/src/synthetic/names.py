import random

_CARRIER_FIRST_WORDS = [
    "IBRAHIM", "DELTA", "PRAIRIE", "SUMMIT", "LONE STAR", "GULF COAST", "RIO GRANDE",
    "BLUE RIDGE", "SILVER CREEK", "COPPER STATE", "RED RIVER", "PALMETTO", "BAYOU",
    "CASCADE", "TIMBER", "HIGHLAND", "SUNRISE", "EAGLE", "LONGHORN", "IRONCLAD",
    "PIONEER", "LIBERTY", "PATRIOT", "FRONTIER", "MERIDIAN", "APEX", "VANGUARD",
    "TITAN", "ATLAS", "HORIZON", "GRANITE", "CROSSROADS", "HERITAGE", "KEYSTONE",
]
_CARRIER_TYPE_WORDS = ["TRANSPORT", "TRUCKING", "LOGISTICS", "FREIGHT", "CARRIERS", "HAULING", "EXPRESS", "LINES"]
_CARRIER_SUFFIXES = ["INC", "LLC", "CORP", "CO"]

_CUSTOMER_REGION_WORDS = [
    "Lone Star", "Alamo", "Gulf Coast", "Rio Grande", "Bayou", "Palmetto", "Blue Ridge",
    "Cascade", "Prairie", "Highland", "Frontier", "Meridian", "Copper State", "Silver Creek",
    "Red River", "Longhorn", "Timber", "Sunrise", "Eagle", "Liberty", "Heritage", "Crossroads",
]
_CUSTOMER_INDUSTRY_WORDS = [
    "Beverages", "Building Supply", "Foods", "Manufacturing", "Distributors", "Wholesale",
    "Produce", "Hardware", "Electronics", "Textiles", "Packaging", "Chemicals", "Auto Parts",
    "Furniture", "Appliances", "Paper Goods", "Industrial Supply",
]


def _generate_unique_names(rng: random.Random, count: int, builder) -> list[str]:
    """Draws `count` unique names via `builder(rng)`, preserving RNG draw
    order in the returned list. Deliberately does NOT use a set for the
    final output ordering -- Python's string hash randomization means set
    iteration order isn't guaranteed reproducible across process runs even
    with a fixed random.Random seed, which would silently break
    determinism. The set here is used only for O(1) membership testing."""
    seen: set[str] = set()
    names: list[str] = []
    while len(names) < count:
        name = builder(rng)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def generate_carrier_names(rng: random.Random, count: int) -> list[str]:
    def build(rng: random.Random) -> str:
        first = rng.choice(_CARRIER_FIRST_WORDS)
        type_word = rng.choice(_CARRIER_TYPE_WORDS)
        suffix = rng.choice(_CARRIER_SUFFIXES)
        return f"{first} {type_word} {suffix}"

    return _generate_unique_names(rng, count, build)


def generate_customer_names(rng: random.Random, count: int) -> list[str]:
    def build(rng: random.Random) -> str:
        region = rng.choice(_CUSTOMER_REGION_WORDS)
        industry = rng.choice(_CUSTOMER_INDUSTRY_WORDS)
        return f"{region} {industry}"

    return _generate_unique_names(rng, count, build)


def generate_unique_number(rng: random.Random, used: set[str], low: int, high: int) -> str:
    """Draws a random integer (as a string) in [low, high] not already in
    `used`, adds it to `used`, and returns it. Caller owns the `used` set
    across multiple calls to guarantee uniqueness within, e.g., one world."""
    while True:
        candidate = str(rng.randint(low, high))
        if candidate not in used:
            used.add(candidate)
            return candidate


def generate_phone_number(rng: random.Random) -> str:
    """Plain 10-digit string (e.g. '5125550199'), not formatted for any
    particular TMS -- formatting is a serialization-time concern, since
    our real fixtures show each source uses a different phone format."""
    area_code = rng.randint(200, 989)  # avoid N11 / invalid leading digits well enough for synthetic data
    exchange = rng.randint(200, 989)
    line = rng.randint(1000, 9999)
    return f"{area_code}{exchange}{line}"
