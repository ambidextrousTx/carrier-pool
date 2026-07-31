from geo.reference_data import GEO_ZIPS, GeoZip

_BY_ZIP: dict[str, GeoZip] = {z.zip_code: z for z in GEO_ZIPS}


def resolve_zip(zip_code: str) -> GeoZip | None:
    """Returns the reference entry for a zip code, or None if it's not in
    our reference universe. Deliberately does not raise -- callers decide
    how strict to be (e.g. ingestion treats an unresolvable zip as a data
    integrity problem and raises; other callers may want to degrade
    gracefully instead)."""
    return _BY_ZIP.get(zip_code)
