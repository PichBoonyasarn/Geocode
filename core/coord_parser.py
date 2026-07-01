"""
Latitude/longitude extraction from free-form text.
Handles English and Japanese formats including DMS, decimal degrees,
labeled fields, and full-width digits.
"""

import re
import unicodedata


def _normalize(text: str) -> str:
    """Convert full-width digits and punctuation to ASCII half-width."""
    return unicodedata.normalize("NFKC", text)


def _validate(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


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
    # ------------------------------------------------------------------
    m = re.search(
        r"(北緯|南緯)\s*(\d+)\s*度\s*(\d+)\s*分\s*([\d.]+)\s*秒"
        r".{0,200}?"
        r"(東経|西経)\s*(\d+)\s*度\s*(\d+)\s*分\s*([\d.]+)\s*秒",
        norm,
        re.DOTALL,
    )
    if m:
        lat = _dms_to_decimal(m.group(2), m.group(3), m.group(4), m.group(1)[0])
        lon = _dms_to_decimal(m.group(6), m.group(7), m.group(8), m.group(5)[0])
        if _validate(lat, lon):
            return lat, lon

    # ------------------------------------------------------------------
    # Pattern 2: English DMS   35°41'22"N 139°41'30"E
    # ------------------------------------------------------------------
    m = re.search(
        r"(\d{1,3})\s*[°度]\s*(\d{1,2})\s*[\'′']\s*([\d.]+)\s*[\"″\"]?\s*([NSns])"
        r"[\s,/;]+(\d{1,3})\s*[°度]\s*(\d{1,2})\s*[\'′']\s*([\d.]+)\s*[\"″\"]?\s*([EWew])",
        norm,
    )
    if m:
        lat = _dms_to_decimal(m.group(1), m.group(2), m.group(3), m.group(4))
        lon = _dms_to_decimal(m.group(5), m.group(6), m.group(7), m.group(8))
        if _validate(lat, lon):
            return lat, lon

    # ------------------------------------------------------------------
    # Pattern 3: Labeled decimal — 緯度: 35.6895 / 経度: 139.6917
    # Also handles latitude/longitude, lat/lon, lat/lng
    # ------------------------------------------------------------------
    m = re.search(
        r"(?:緯度|北緯|lat(?:itude)?)\s*[：:=\s]\s*([-\d.]+)"
        r".{0,300}?"
        r"(?:経度|東経|lon(?:gitude)?|lng)\s*[：:=\s]\s*([-\d.]+)",
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

    return None
