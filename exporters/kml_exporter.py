"""
KML / KMZ export from extraction results.
"""

import os
import tempfile
from pathlib import Path

import simplekml


def _build_kml(results: list[dict]) -> simplekml.Kml:
    kml = simplekml.Kml(name="抽出された位置情報")

    for r in results:
        if r.get("status") != "success":
            continue
        lat = r.get("lat")
        lon = r.get("lon")
        if lat is None or lon is None:
            continue

        name = Path(r["filename"]).stem
        pnt = kml.newpoint(name=name)
        pnt.coords = [(lon, lat, 0)]  # KML order: lon, lat, altitude
        snippet = r.get("snippet", "")
        pnt.description = (
            f"ファイル: {r['filename']}\n"
            f"取得方法: {r.get('method', '')}\n"
            f"緯度: {lat:.6f}\n"
            f"経度: {lon:.6f}\n"
            + (f"\n抜粋: {snippet}" if snippet else "")
        )

    return kml


def export_kml_bytes(results: list[dict]) -> bytes:
    """Return KML file content as bytes (UTF-8)."""
    kml = _build_kml(results)
    return kml.kml().encode("utf-8")


def export_kmz_bytes(results: list[dict]) -> bytes:
    """Return KMZ (zipped KML) file content as bytes."""
    kml = _build_kml(results)

    fd, tmp_path = tempfile.mkstemp(suffix=".kmz")
    os.close(fd)
    try:
        kml.savekmz(tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
