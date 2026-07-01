"""
Vision AI wrapper for extracting lat/lon from map images embedded in documents.
Supports Claude Vision API (default) and a Google Vision + Geocoding fallback.
"""

import base64
import os
from typing import Optional

from core.coord_parser import extract_coordinates


def analyze_map_image(image_bytes: bytes, backend: str = "claude") -> Optional[tuple[float, float]]:
    """
    Send a map image to the chosen vision backend and return (lat, lon) or None.
    """
    if backend == "claude":
        return _claude(image_bytes)
    if backend == "google":
        return _google(image_bytes)
    return None


# ------------------------------------------------------------------
# Claude Vision backend
# ------------------------------------------------------------------

_CLAUDE_PROMPT = (
    "この画像は文書に埋め込まれた地図です。日本国内の地図である可能性が高いです。\n"
    "地図に示されている中心付近の場所の緯度・経度を特定してください。\n"
    "必ず次の形式だけで回答してください（他の文章は不要です）:\n"
    "LAT: 35.6895\n"
    "LON: 139.6917\n\n"
    "This is a map image embedded in a document, likely showing a location in Japan. "
    "Identify the location at or near the center of the map. "
    "Reply ONLY with:\n"
    "LAT: <decimal degrees>\n"
    "LON: <decimal degrees>"
)


def _claude(image_bytes: bytes) -> Optional[tuple[float, float]]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    try:
        import anthropic

        media_type = _detect_media_type(image_bytes)
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": _CLAUDE_PROMPT},
                    ],
                }
            ],
        )

        reply = response.content[0].text
        return extract_coordinates(reply)

    except Exception:
        return None


# ------------------------------------------------------------------
# Google Vision + Geocoding backend (placeholder)
# ------------------------------------------------------------------

def _google(image_bytes: bytes) -> Optional[tuple[float, float]]:
    """
    Uses Google Cloud Vision OCR to read text from the map image,
    then geocodes the best place-name candidate.
    Requires: google-cloud-vision and googlemaps packages + GOOGLE_MAPS_API_KEY.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return None

    try:
        from google.cloud import vision  # type: ignore
        import googlemaps  # type: ignore

        vision_client = vision.ImageAnnotatorClient()
        image = vision.Image(content=image_bytes)
        response = vision_client.text_detection(image=image)

        if not response.text_annotations:
            return None

        raw_text = response.text_annotations[0].description

        # Try to parse coords directly from OCR'd text first
        coords = extract_coordinates(raw_text)
        if coords:
            return coords

        # Otherwise take first significant text block and geocode it
        gmaps = googlemaps.Client(key=api_key)
        geocode_result = gmaps.geocode(raw_text[:200], language="ja", region="jp")
        if geocode_result:
            loc = geocode_result[0]["geometry"]["location"]
            return loc["lat"], loc["lng"]

    except Exception:
        return None

    return None


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def _detect_media_type(data: bytes) -> str:
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"
