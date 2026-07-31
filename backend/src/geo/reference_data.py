from dataclasses import dataclass


@dataclass(frozen=True)
class GeoZip:
    zip_code: str
    city: str
    state: str
    latitude: float
    longitude: float
    market_area: str


# Deliberately concentrated on a bounded set of ~18 market areas across
# major US freight corridors (Texas Triangle, Southeast, Midwest, plus a
# few West Coast/Mountain anchors for variety) rather than scattered
# uniformly nationwide -- so that lanes in generated synthetic data
# actually repeat, which is the whole point of this table existing.
#
# Includes every zip that already appears in our real uploaded TMS
# fixtures (Grand Prairie, Katy, New Braunfels, Pasadena, Sugar Land,
# Schertz), so ingestion of that real sample data resolves cleanly too.
_RAW_ZIPS: list[tuple[str, str, str, float, float, str]] = [
    # zip, city, state, lat, lon, market_area
    # --- Dallas-Fort Worth Metro ---
    ("75201", "Dallas", "TX", 32.78, -96.80, "Dallas-Fort Worth Metro"),
    ("76102", "Fort Worth", "TX", 32.75, -97.33, "Dallas-Fort Worth Metro"),
    ("75050", "Grand Prairie", "TX", 32.75, -97.02, "Dallas-Fort Worth Metro"),
    ("76010", "Arlington", "TX", 32.74, -97.11, "Dallas-Fort Worth Metro"),
    ("75061", "Irving", "TX", 32.81, -96.95, "Dallas-Fort Worth Metro"),
    # --- Houston Metro ---
    ("77002", "Houston", "TX", 29.76, -95.37, "Houston Metro"),
    ("77449", "Katy", "TX", 29.79, -95.82, "Houston Metro"),
    ("77502", "Pasadena", "TX", 29.69, -95.21, "Houston Metro"),
    ("77478", "Sugar Land", "TX", 29.62, -95.63, "Houston Metro"),
    ("77520", "Baytown", "TX", 29.73, -94.98, "Houston Metro"),
    # --- San Antonio Metro ---
    ("78205", "San Antonio", "TX", 29.42, -98.49, "San Antonio Metro"),
    ("78130", "New Braunfels", "TX", 29.70, -98.12, "San Antonio Metro"),
    ("78154", "Schertz", "TX", 29.55, -98.27, "San Antonio Metro"),
    # --- Austin Metro ---
    ("78701", "Austin", "TX", 30.27, -97.74, "Austin Metro"),
    ("78664", "Round Rock", "TX", 30.51, -97.68, "Austin Metro"),
    ("78626", "Georgetown", "TX", 30.63, -97.68, "Austin Metro"),
    # --- Memphis Metro ---
    ("38103", "Memphis", "TN", 35.15, -90.05, "Memphis Metro"),
    ("38671", "Southaven", "MS", 34.99, -90.03, "Memphis Metro"),
    # --- Atlanta Metro ---
    ("30303", "Atlanta", "GA", 33.75, -84.39, "Atlanta Metro"),
    ("30060", "Marietta", "GA", 33.95, -84.55, "Atlanta Metro"),
    ("30030", "Decatur", "GA", 33.77, -84.30, "Atlanta Metro"),
    # --- Chicago Metro ---
    ("60601", "Chicago", "IL", 41.89, -87.62, "Chicago Metro"),
    ("60432", "Joliet", "IL", 41.53, -88.08, "Chicago Metro"),
    ("60505", "Aurora", "IL", 41.76, -88.30, "Chicago Metro"),
    # --- NYC / NJ Metro ---
    ("07102", "Newark", "NJ", 40.74, -74.17, "NYC Metro"),
    ("07302", "Jersey City", "NJ", 40.72, -74.04, "NYC Metro"),
    ("07201", "Elizabeth", "NJ", 40.66, -74.21, "NYC Metro"),
    ("11201", "Brooklyn", "NY", 40.69, -73.99, "NYC Metro"),
    # --- Charlotte Metro ---
    ("28202", "Charlotte", "NC", 35.23, -80.84, "Charlotte Metro"),
    ("28025", "Concord", "NC", 35.41, -80.58, "Charlotte Metro"),
    # --- Nashville Metro ---
    ("37203", "Nashville", "TN", 36.15, -86.78, "Nashville Metro"),
    ("37130", "Murfreesboro", "TN", 35.85, -86.39, "Nashville Metro"),
    # --- Kansas City Metro ---
    ("64106", "Kansas City", "MO", 39.10, -94.58, "Kansas City Metro"),
    ("66101", "Kansas City", "KS", 39.11, -94.63, "Kansas City Metro"),
    ("66061", "Olathe", "KS", 38.88, -94.82, "Kansas City Metro"),
    # --- St. Louis Metro ---
    ("63101", "St. Louis", "MO", 38.63, -90.20, "St. Louis Metro"),
    ("62201", "East St. Louis", "IL", 38.62, -90.15, "St. Louis Metro"),
    # --- Oklahoma City Metro ---
    ("73102", "Oklahoma City", "OK", 35.47, -97.52, "Oklahoma City Metro"),
    ("73069", "Norman", "OK", 35.22, -97.44, "Oklahoma City Metro"),
    # --- Indianapolis Metro ---
    ("46204", "Indianapolis", "IN", 39.77, -86.16, "Indianapolis Metro"),
    ("46168", "Plainfield", "IN", 39.70, -86.40, "Indianapolis Metro"),
    # --- Columbus Metro ---
    ("43215", "Columbus", "OH", 39.96, -83.00, "Columbus Metro"),
    ("43123", "Grove City", "OH", 39.88, -83.09, "Columbus Metro"),
    # --- Phoenix Metro ---
    ("85003", "Phoenix", "AZ", 33.45, -112.07, "Phoenix Metro"),
    ("85281", "Tempe", "AZ", 33.43, -111.94, "Phoenix Metro"),
    ("85201", "Mesa", "AZ", 33.42, -111.83, "Phoenix Metro"),
    # --- Denver Metro ---
    ("80202", "Denver", "CO", 39.75, -104.99, "Denver Metro"),
    ("80010", "Aurora", "CO", 39.73, -104.83, "Denver Metro"),
    # --- LA / Inland Empire ---
    ("90012", "Los Angeles", "CA", 34.06, -118.24, "Los Angeles / Inland Empire"),
    ("91761", "Ontario", "CA", 34.06, -117.65, "Los Angeles / Inland Empire"),
    ("92335", "Fontana", "CA", 34.09, -117.44, "Los Angeles / Inland Empire"),
]

GEO_ZIPS: list[GeoZip] = [GeoZip(*row) for row in _RAW_ZIPS]
