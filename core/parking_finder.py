"""
Automatic parking spot finder.

Pipeline per cluster of inspection points:
  1. Cluster nearby points to avoid redundant searches
  2. Query OSM Overpass for drivable road segments in radius
  3. Sample candidate points along those roads
  4. Fetch Google Street View image for each candidate
  5. Ask Claude Vision: is this viable for temporary government parking?
  6. Return YES spots as parking pin data
"""

import base64
import math
import os
from typing import Callable, Optional

import requests

# ─────────────────────────────────────────────
# Public: clustering
# ─────────────────────────────────────────────

def cluster_points(points: list[dict], radius_m: int = 400) -> list[dict]:
    """
    Group inspection points that are within radius_m of each other.
    Uses greedy nearest-cluster assignment.

    Input:  list of dicts with 'lat', 'lon', 'filename'
    Output: list of cluster dicts with 'center_lat', 'center_lon', 'members'
    """
    clusters: list[dict] = []

    for pt in points:
        assigned = False
        for cl in clusters:
            dist = _haversine(pt["lat"], pt["lon"], cl["center_lat"], cl["center_lon"])
            if dist <= radius_m:
                cl["members"].append(pt["filename"])
                # Update center to mean of all members
                all_lats = [p["lat"] for p in points if p["filename"] in cl["members"]]
                all_lons = [p["lon"] for p in points if p["filename"] in cl["members"]]
                cl["center_lat"] = sum(all_lats) / len(all_lats)
                cl["center_lon"] = sum(all_lons) / len(all_lons)
                assigned = True
                break
        if not assigned:
            clusters.append({
                "center_lat": pt["lat"],
                "center_lon": pt["lon"],
                "members": [pt["filename"]],
            })

    return clusters


# ─────────────────────────────────────────────
# Public: main search
# ─────────────────────────────────────────────

def find_parking_for_clusters(
    clusters: list[dict],
    google_api_key: str = "",
    anthropic_api_key: str = "",
    radius_m: int = 400,
    max_candidates: int = 8,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> tuple[list[dict], list[dict]]:
    """
    For each cluster, find viable temporary parking spots nearby.

    Returns:
        (parking_spots, diagnostics)
        parking_spots: list of {lat, lon, reason, serves, distance_m}
        diagnostics:   list of per-cluster diagnostic dicts
    """
    results: list[dict] = []
    diagnostics: list[dict] = []
    total = len(clusters)

    for i, cluster in enumerate(clusters):
        if progress_callback:
            members_str = "、".join(cluster["members"][:2])
            if len(cluster["members"]) > 2:
                members_str += f" 他{len(cluster['members'])-2}件"
            progress_callback(i, total, members_str)

        spots, diag = _search_cluster(
            cluster["center_lat"],
            cluster["center_lon"],
            radius_m=radius_m,
            max_candidates=max_candidates,
            google_api_key=google_api_key,
            anthropic_api_key=anthropic_api_key,
        )
        diag["cluster_members"] = cluster["members"]
        diag["center_lat"] = cluster["center_lat"]
        diag["center_lon"] = cluster["center_lon"]
        diagnostics.append(diag)

        for spot in spots:
            spot["serves"] = cluster["members"]
            results.append(spot)

    if progress_callback:
        progress_callback(total, total, "")

    return results, diagnostics


# ─────────────────────────────────────────────
# Internal: per-cluster search
# ─────────────────────────────────────────────

def _search_cluster(
    lat: float,
    lon: float,
    radius_m: int,
    max_candidates: int,
    google_api_key: str,
    anthropic_api_key: str,
) -> tuple[list[dict], dict]:
    diag = {
        "osm_candidates": 0,
        "streetview_fetched": 0,
        "streetview_no_coverage": 0,
        "streetview_statuses": {},  # status → count, e.g. {"REQUEST_DENIED": 5}
        "ai_yes": 0,
        "ai_no": 0,
        "ai_errors": [],
        "osm_error": None,
    }

    candidates, osm_error = _get_road_candidates(lat, lon, radius_m)
    diag["osm_candidates"] = len(candidates)
    diag["osm_error"] = osm_error
    parking_spots: list[dict] = []

    for cand in candidates[:max_candidates]:
        img_bytes, sv_status = _fetch_streetview(cand["lat"], cand["lon"], google_api_key)
        if img_bytes is None:
            diag["streetview_no_coverage"] += 1
            diag["streetview_statuses"][sv_status] = diag["streetview_statuses"].get(sv_status, 0) + 1
            continue

        diag["streetview_fetched"] += 1
        ok, reason = _assess_parking(img_bytes, anthropic_api_key)

        if reason.startswith("エラー"):
            diag["ai_errors"].append(reason)
        elif ok:
            diag["ai_yes"] += 1
            parking_spots.append({
                "lat": cand["lat"],
                "lon": cand["lon"],
                "reason": reason,
                "distance_m": int(_haversine(lat, lon, cand["lat"], cand["lon"])),
            })
        else:
            diag["ai_no"] += 1

    return parking_spots, diag


# ─────────────────────────────────────────────
# Internal: OSM road candidate sampling
# ─────────────────────────────────────────────

_PARKABLE_ROAD_TYPES = "residential|service|tertiary|unclassified|living_street"
# Primary + fallback Overpass API mirrors
_OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
_SAMPLE_INTERVAL_M = 60
_DEDUP_RADIUS_M = 30


def _get_road_candidates(lat: float, lon: float, radius_m: int) -> tuple[list[dict], str | None]:
    """
    Query OSM for drivable road segments within radius_m, then sample
    points every _SAMPLE_INTERVAL_M metres along each segment.
    Returns (candidates, error_message_or_None).
    """
    query = (
        f"[out:json][timeout:25];"
        f'way["highway"~"^({_PARKABLE_ROAD_TYPES})$"](around:{radius_m},{lat},{lon});'
        f"out body geom;"
    )
    headers = {"User-Agent": "geo_extractor/1.0 (government inspection support tool)"}
    last_error = None
    data = None

    for url in _OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            last_error = None
            break
        except Exception as e:
            last_error = f"OSMクエリ失敗 ({url}): {e}"

    if data is None:
        return [], last_error

    raw_points: list[dict] = []
    for way in data.get("elements", []):
        geometry = way.get("geometry", [])
        for j in range(len(geometry) - 1):
            p1 = geometry[j]
            p2 = geometry[j + 1]
            segment_len = _haversine(p1["lat"], p1["lon"], p2["lat"], p2["lon"])
            steps = max(1, int(segment_len / _SAMPLE_INTERVAL_M))
            for k in range(steps + 1):
                frac = k / steps if steps else 0
                slat = p1["lat"] + frac * (p2["lat"] - p1["lat"])
                slon = p1["lon"] + frac * (p2["lon"] - p1["lon"])
                # Only keep points within the search radius
                if _haversine(lat, lon, slat, slon) <= radius_m:
                    raw_points.append({"lat": slat, "lon": slon})

    return _deduplicate(raw_points, _DEDUP_RADIUS_M), None


def _deduplicate(points: list[dict], min_dist_m: float) -> list[dict]:
    """Remove points that are closer than min_dist_m to an already-kept point."""
    kept: list[dict] = []
    for pt in points:
        too_close = any(
            _haversine(pt["lat"], pt["lon"], k["lat"], k["lon"]) < min_dist_m
            for k in kept
        )
        if not too_close:
            kept.append(pt)
    return kept


# ─────────────────────────────────────────────
# Internal: Street View image fetch
# ─────────────────────────────────────────────

_SV_URL = "https://maps.googleapis.com/maps/api/streetview"
_SV_META_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"


def _fetch_streetview(lat: float, lon: float, api_key: str) -> tuple[Optional[bytes], str]:
    """
    Fetch a 640×480 Street View image.
    Returns (image_bytes_or_None, status_string).
    Status is "OK", "NO_COVERAGE", "REQUEST_DENIED", "API_ERROR", or "FETCH_ERROR".
    """
    if not api_key:
        return None, "NO_KEY"

    # Check coverage first (metadata call is free)
    try:
        meta = requests.get(
            _SV_META_URL,
            params={"location": f"{lat},{lon}", "key": api_key},
            timeout=10,
        ).json()
        sv_status = meta.get("status", "UNKNOWN")
        if sv_status != "OK":
            return None, sv_status
    except Exception as e:
        return None, f"API_ERROR:{e}"

    try:
        resp = requests.get(
            _SV_URL,
            params={
                "size": "640x480",
                "location": f"{lat},{lon}",
                "fov": "90",
                "heading": "0",
                "key": api_key,
            },
            timeout=15,
        )
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image"):
            return resp.content, "OK"
    except Exception as e:
        return None, f"FETCH_ERROR:{e}"

    return None, "FETCH_ERROR"

    try:
        resp = requests.get(
            _SV_URL,
            params={
                "size": "640x480",
                "location": f"{lat},{lon}",
                "fov": "90",
                "heading": "0",  # north-facing; sufficient for road width assessment
                "key": api_key,
            },
            timeout=15,
        )
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image"):
            return resp.content
    except Exception:
        pass

    return None


# ─────────────────────────────────────────────
# Internal: Claude Vision parking assessment
# ─────────────────────────────────────────────

_PARKING_PROMPT = """\
この画像は日本のGoogle Street Viewです。
政府機関の道路点検作業員が、作業中に車両を道路脇に一時的に駐車する必要があります。
専用の駐車場は不要です。「作業中」の標識を立てることを前提に、\
交通を大きく妨げずに1台（普通乗用車サイズ）を停車できるスペースがあるかどうか判断してください。

広い路肩、サービス道路、交通量の少ない住宅街の道路側などは適しています。
幹線道路、狭い路地、駐車が明らかに困難な場所は不適です。

必ず次の形式だけで回答してください（他の文章は不要）:
PARKABLE: YES
REASON: <駐停車可能な理由を1文で>

または:
PARKABLE: NO
REASON: <不適な理由を1文で>

This is a Google Street View image in Japan. \
Government inspection workers need to temporarily park one vehicle roadside. \
Reply ONLY in the format above — PARKABLE: YES/NO then REASON in Japanese."""


def _assess_parking(image_bytes: bytes, api_key: str) -> tuple[bool, str]:
    """
    Send Street View image to Claude Vision.
    Auto-detects backend from key prefix:
      sk-or-…  → OpenRouter (OpenAI-compatible endpoint)
      sk-ant-… → Anthropic SDK (direct)
    Returns (is_parkable, reason_japanese).
    """
    if not api_key:
        return False, "APIキーが設定されていません"

    if api_key.startswith("sk-or-"):
        return _assess_via_openrouter(image_bytes, api_key)
    return _assess_via_anthropic(image_bytes, api_key)


def _assess_via_anthropic(image_bytes: bytes, api_key: str) -> tuple[bool, str]:
    try:
        import anthropic

        media_type = _detect_media_type(image_bytes)
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=120,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": _PARKING_PROMPT},
                ],
            }],
        )
        return _parse_assessment(response.content[0].text.strip())
    except Exception as e:
        return False, f"エラー (Anthropic): {e}"


def _assess_via_openrouter(image_bytes: bytes, api_key: str) -> tuple[bool, str]:
    try:
        media_type = _detect_media_type(image_bytes)
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{media_type};base64,{b64}"

        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "anthropic/claude-sonnet-4-5",
                "max_tokens": 120,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": _PARKING_PROMPT},
                    ],
                }],
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        return _parse_assessment(text)
    except Exception as e:
        return False, f"エラー (OpenRouter): {e}"


def _parse_assessment(text: str) -> tuple[bool, str]:
    parkable = False
    reason = text
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("PARKABLE:"):
            parkable = "YES" in line.upper()
        elif line.upper().startswith("REASON:"):
            reason = line.split(":", 1)[-1].strip()
    return parkable, reason


# ─────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two lat/lon points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _detect_media_type(data: bytes) -> str:
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    return "image/jpeg"
