"""
Document processing pipeline.
Orchestrates readers → coord_parser → image_analyzer for each file.
"""

import sys
import os
from pathlib import Path
from typing import Callable, Optional

# Ensure project root is on path when run as a module
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from readers.pdf_reader import extract_text_and_images as _pdf
from readers.word_reader import extract_text_and_images as _word
from readers.excel_reader import extract_text_and_images as _excel
from core.coord_parser import extract_coordinates
from core.image_analyzer import analyze_map_image

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls"}

ProgressCallback = Callable[[int, int, str], None]


def process_document(file_path: str, vision_backend: str = "claude") -> dict:
    """
    Process a single document file.

    Returns a dict with keys:
        filename, filepath, lat, lon, method, status, snippet
    """
    path = Path(file_path)
    result: dict = {
        "filename": path.name,
        "filepath": str(path),
        "lat": None,
        "lon": None,
        "method": None,
        "status": "processing",
        "snippet": "",
    }

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        result["status"] = "unsupported"
        result["method"] = "非対応形式"
        return result

    try:
        if ext == ".pdf":
            text, images = _pdf(str(path))
        elif ext == ".docx":
            text, images = _word(str(path))
        else:  # .xlsx / .xls
            text, images = _excel(str(path))

        # --- Step 1: text-based extraction ---
        coords = extract_coordinates(text)
        if coords:
            result["lat"], result["lon"] = coords
            result["method"] = "テキスト抽出"
            result["status"] = "success"
            result["snippet"] = _snippet(text, coords[0])
            return result

        # --- Step 2: map image analysis ---
        if images and vision_backend not in ("none", "なし（スキップ）", ""):
            has_key = bool(
                os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("GOOGLE_MAPS_API_KEY")
            )
            if has_key:
                for img_bytes in images:
                    coords = analyze_map_image(img_bytes, backend=vision_backend)
                    if coords:
                        result["lat"], result["lon"] = coords
                        result["method"] = "地図画像解析"
                        result["status"] = "success"
                        return result

        # --- Step 3: nothing found ---
        result["status"] = "manual_review"
        result["method"] = "手動確認が必要"

    except Exception as exc:
        result["status"] = "error"
        result["method"] = f"エラー: {exc}"

    return result


def scan_folder(
    folder_path: str,
    vision_backend: str = "claude",
    progress_callback: Optional[ProgressCallback] = None,
) -> list[dict]:
    """
    Scan all supported files in folder_path and return a list of result dicts.
    progress_callback(current_index, total, current_filename) is called each step.
    """
    folder = Path(folder_path)
    files = sorted(
        [f for f in folder.iterdir() if f.suffix.lower() in SUPPORTED_EXTENSIONS]
    )
    results: list[dict] = []

    for i, file_path in enumerate(files):
        if progress_callback:
            progress_callback(i, len(files), file_path.name)
        result = process_document(str(file_path), vision_backend=vision_backend)
        results.append(result)

    if progress_callback:
        progress_callback(len(files), len(files), "")

    return results


def _snippet(text: str, lat: float) -> str:
    probe = str(round(abs(lat), 2))
    idx = text.find(probe)
    if idx == -1:
        return ""
    start = max(0, idx - 30)
    end = min(len(text), idx + 80)
    return text[start:end].strip().replace("\n", " ")
