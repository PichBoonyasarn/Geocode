"""
Latitude/longitude extraction from free-form text.
Handles English and Japanese formats including DMS, decimal degrees,
labeled fields, and full-width digits.
"""

import re
import unicodedata

from core.plane_rectangular import plane_rectangular_to_latlon

# Japan bounding box, used to gate looser patterns (direction-optional DMS,
# label-proximity scan, plane-rectangular conversion) where a global -90/90,
# -180/180 check would let through too many false positives.
_JP_LAT_MIN, _JP_LAT_MAX = 24.0, 46.0
_JP_LON_MIN, _JP_LON_MAX = 122.0, 154.0


def _normalize(text: str) -> str:
    """Convert full-width digits and punctuation to ASCII half-width."""
    return unicodedata.normalize("NFKC", text)


def _validate(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _validate_japan(lat: float, lon: float) -> bool:
    return _JP_LAT_MIN <= lat <= _JP_LAT_MAX and _JP_LON_MIN <= lon <= _JP_LON_MAX


def _dms_to_decimal(degrees: str, minutes: str | None, seconds: str | None, direction: str) -> float:
    d = float(degrees)
    m = float(minutes) if minutes else 0.0
    s = float(seconds) if seconds else 0.0
    value = d + m / 60.0 + s / 3600.0
    if direction.upper() in ("S", "W", "南", "西"):
        value = -value
    return value


def _find_snippet(text: str, lat: float, lon: float) -> str:
    """Return a short text snippet near where the coordinates appeared."""
    probe = str(round(abs(lat), 2))
    idx = text.find(probe)
    if idx == -1:
        return ""
    start = max(0, idx - 30)
    end = min(len(text), idx + 80)
    return text[start:end].strip().replace("\n", " ")


def extract_coordinates(text: str) -> tuple[float, float] | None:
    """
    Try every known coordinate pattern on the text.
    Returns (lat, lon) in decimal degrees, or None if nothing found.
    """
    norm = _normalize(text)

    # ------------------------------------------------------------------
    # Pattern 1: Japanese DMS
    # 北緯35度41分22秒 東経139度41分30秒
    # Also accepts the plain 緯度/経度 labels (no 北/東 direction prefix), e.g.
    # 緯度:37度23分48.32秒 経度:136度50分34.33秒 — direction defaults to
    # North/East when unspecified.
    # ------------------------------------------------------------------
    m = re.search(
        r"(北緯|南緯|緯度)\s*[:：]?\s*(\d+)\s*度\s*(\d+)\s*分\s*([\d.]+)\s*秒"
        r".{0,200}?"
        r"(東経|西経|経度)\s*[:：]?\s*(\d+)\s*度\s*(\d+)\s*分\s*([\d.]+)\s*秒",
        norm,
        re.DOTALL,
    )
    if m:
        lat_dir = "南" if m.group(1) == "南緯" else "北"
        lon_dir = "西" if m.group(5) == "西経" else "東"
        lat = _dms_to_decimal(m.group(2), m.group(3), m.group(4), lat_dir)
        lon = _dms_to_decimal(m.group(6), m.group(7), m.group(8), lon_dir)
        if _validate(lat, lon):
            return lat, lon

    # ------------------------------------------------------------------
    # Pattern 2: English/symbol DMS   35°41'22"N 139°41'30"E
    # The N/E direction letter is optional — some inspection-form documents
    # print bare "34°53′37.33″ 135°12′14.98″" with no suffix, defaulting to
    # North/East. Also tolerates 北緯/緯度 and 東経/経度 kanji labels wrapping
    # symbol-based DMS (e.g. "北緯 37°22′36.4″ 東経 139°15′30.2″"), where the
    # 東経/経度 label sits between the two DMS groups rather than as a plain
    # prefix. Because direction is optional here, validate against Japan's
    # bounding box specifically to avoid matching unrelated angle values.
    # ------------------------------------------------------------------
    m = re.search(
        r"(?:北緯|緯度)?\s*(\d{1,3})\s*[°度˚]\s*(\d{1,2})\s*[\'′]\s*([\d.]+)\s*(?:[\"″]|[′\']{2})?\s*([NSns])?"
        r"\s*[,、\s]*(?:東経|経度)?\s*(\d{1,3})\s*[°度˚]\s*(\d{1,2})\s*[\'′]\s*([\d.]+)\s*(?:[\"″]|[′\']{2})?\s*([EWew])?",
        norm,
    )
    if m:
        lat_dir = m.group(4) or "N"
        lon_dir = m.group(8) or "E"
        lat = _dms_to_decimal(m.group(1), m.group(2), m.group(3), lat_dir)
        lon = _dms_to_decimal(m.group(5), m.group(6), m.group(7), lon_dir)
        if _validate_japan(lat, lon):
            return lat, lon

    # ------------------------------------------------------------------
    # Pattern 3: Labeled decimal — 緯度: 35.6895 / 経度: 139.6917
    # Also handles latitude/longitude, lat/lon, lat/lng
    # The two lookaheads after each capture reject a match whose number is
    # immediately followed by a degree symbol — without them, a label
    # sitting next to a DMS value like "緯度: 35°41'22\"" would truncate at
    # the degree sign and silently misread "35" as a bare decimal 35.0.
    # A single "(?!\s*[°度˚])" isn't enough: since [-\d.]+ is greedy but can
    # backtrack, the engine would just retry with a shorter match ("3") to
    # satisfy the lookahead, misreading it as 3.0 instead. Requiring "next
    # char isn't a digit" first forces the quantifier to consume the whole
    # contiguous number before the degree-symbol lookahead is even checked.
    # ------------------------------------------------------------------
    m = re.search(
        r"(?:緯度|北緯|lat(?:itude)?)\s*[：:=\s]\s*([-\d.]+)(?!\d)(?!\s*[°度˚])"
        r".{0,300}?"
        r"(?:経度|東経|lon(?:gitude)?|lng)\s*[：:=\s]\s*([-\d.]+)(?!\d)(?!\s*[°度˚])",
        norm,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        try:
            lat, lon = float(m.group(1)), float(m.group(2))
            if _validate(lat, lon):
                return lat, lon
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Pattern 4: Decimal with direction indicator
    # 35.6895N, 139.6917E  or  35.6895°N 139.6917°E
    # ------------------------------------------------------------------
    m = re.search(
        r"([\d.]+)\s*°?\s*([NSns南北])"
        r"[\s,/;]+"
        r"([\d.]+)\s*°?\s*([EWew東西])",
        norm,
    )
    if m:
        try:
            lat = float(m.group(1))
            if m.group(2).upper() in ("S", "南"):
                lat = -lat
            lon = float(m.group(3))
            if m.group(4).upper() in ("W", "西"):
                lon = -lon
            if _validate(lat, lon):
                return lat, lon
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Pattern 5: Bare decimal pair — 35.6895, 139.6917
    # Require at least 4 decimal places to reduce noise.
    # ------------------------------------------------------------------
    candidates = re.findall(r"-?(?:\d{1,3})\.(\d{4,})", norm)
    all_decimals = re.findall(r"-?\d{1,3}\.\d{4,}", norm)
    for i in range(len(all_decimals) - 1):
        try:
            a, b = float(all_decimals[i]), float(all_decimals[i + 1])
            if _validate(a, b):
                return a, b
            # Maybe order is lon, lat
            if _validate(b, a):
                return b, a
        except ValueError:
            continue

    # ------------------------------------------------------------------
    # Pattern 6: Label-proximity scan
    # Handles documents where the 緯度/経度 label and its value are far
    # apart, duplicated, or tab-separated instead of adjacent (common in
    # flattened multi-page PDF tables), e.g. "経度 経度\t137.454318".
    # ------------------------------------------------------------------
    lat_hit = _find_nearby_labeled_value(norm, _LAT_KEYWORDS, is_lon=False)
    lon_hit = _find_nearby_labeled_value(norm, _LON_KEYWORDS, is_lon=True)
    if lat_hit is not None and lon_hit is not None:
        return lat_hit, lon_hit

    # ------------------------------------------------------------------
    # Pattern 7: Japan Plane Rectangular Coordinate System (平面直角座標系)
    # A genuinely different coordinate system (meters from one of 19 zone
    # origins, not degrees) seen in bridge/civil-engineering inspection
    # forms, e.g. "平面直角座標系 VII系 X=-31236.4333 Y=-46496.4082".
    # ------------------------------------------------------------------
    plane_rect = _find_plane_rectangular(norm)
    if plane_rect and _validate_japan(*plane_rect):
        return plane_rect

    return None


# ------------------------------------------------------------------
# Pattern 6 helper: label-proximity scan
# ------------------------------------------------------------------

_LAT_KEYWORDS = ("緯度", "北緯")
_LON_KEYWORDS = ("経度", "東経")
_LABEL_PROXIMITY_WINDOW = 300
_PROXIMITY_NUMBER_RE = re.compile(r"\d{1,4}\.\d{3,}")
# DMS fallback for flattened table layouts where the label and its DMS value
# sit next to each other but unrelated cell text (e.g. another column's
# label) intervenes before the matching 緯度/経度 counterpart, breaking the
# contiguous DMS regex (Pattern 2) — e.g. "緯度\n36°58'18.68'' \nIV\n...\n経度\n...".
_PROXIMITY_DMS_RE = re.compile(r"(\d{1,3})\s*[°度˚]\s*(\d{1,2})\s*[′']\s*([\d.]+)\s*(?:[″\"]|[′']{2})?")


def _find_nearby_labeled_value(text: str, keywords: tuple[str, ...], is_lon: bool) -> float | None:
    """Scan forward from every occurrence of any keyword for the nearest
    plain-decimal or DMS-formatted value (within _LABEL_PROXIMITY_WINDOW
    chars) that falls in Japan's valid lat/lon range, skipping occurrences
    with nothing nearby."""
    lo, hi = (_JP_LON_MIN, _JP_LON_MAX) if is_lon else (_JP_LAT_MIN, _JP_LAT_MAX)
    for kw in keywords:
        search_from = 0
        while True:
            idx = text.find(kw, search_from)
            if idx == -1:
                break
            search_from = idx + len(kw)
            window = text[search_from : search_from + _LABEL_PROXIMITY_WINDOW]

            for num_m in _PROXIMITY_NUMBER_RE.finditer(window):
                value = float(num_m.group())
                if lo <= value <= hi:
                    return value

            dms_m = _PROXIMITY_DMS_RE.search(window)
            if dms_m:
                value = _dms_to_decimal(dms_m.group(1), dms_m.group(2), dms_m.group(3), "E" if is_lon else "N")
                if lo <= value <= hi:
                    return value
    return None


# ------------------------------------------------------------------
# Pattern 7 helper: Japan Plane Rectangular Coordinate System (平面直角座標系)
# ------------------------------------------------------------------

_PLANE_RECT_LABEL = "平面直角座標系"
_PLANE_RECT_ZONE_WINDOW = 30
# X and Y aren't necessarily adjacent to their own labels in flattened
# multi-page tables — a generous forward window covers documents where the
# second value sits thousands of characters after the zone label.
_PLANE_RECT_SEARCH_WINDOW = 5000
_COORD_LIKE_NUMBER_RE = re.compile(r"-?\d{2,6}\.\d{3,}")
_ROMAN_TO_ZONE = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19,
}
_ZONE_TOKEN_RE = re.compile(r"([IVX]+|\d{1,2})\s*系")


def _parse_zone_token(token: str) -> int | None:
    if token.isdigit():
        n = int(token)
        return n if 1 <= n <= 19 else None
    return _ROMAN_TO_ZONE.get(token)


def _find_plane_rectangular(text: str) -> tuple[float, float] | None:
    """Detect a 平面直角座標系 zone label plus its X/Y values and convert to (lat, lon)."""
    zone_idx = text.find(_PLANE_RECT_LABEL)
    if zone_idx == -1:
        return None

    zone_window = text[zone_idx : zone_idx + len(_PLANE_RECT_LABEL) + _PLANE_RECT_ZONE_WINDOW]
    zone_match = _ZONE_TOKEN_RE.search(zone_window)
    zone = _parse_zone_token(zone_match.group(1)) if zone_match else None
    if zone is None:
        return None

    search_start = zone_idx + len(_PLANE_RECT_LABEL)
    window = text[search_start : search_start + _PLANE_RECT_SEARCH_WINDOW]
    hits = [float(m.group()) for m in _COORD_LIKE_NUMBER_RE.finditer(window)][:2]
    if len(hits) < 2:
        return None

    x, y = hits
    return plane_rectangular_to_latlon(x, y, zone)
