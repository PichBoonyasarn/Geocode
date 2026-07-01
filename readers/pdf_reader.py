import fitz  # PyMuPDF
import hashlib
import io
from PIL import Image


def extract_text_and_images(pdf_path: str, max_pages: int = 2) -> tuple[str, list[bytes]]:
    """Extract text and map-candidate images from the first max_pages pages of a PDF."""
    doc = fitz.open(pdf_path)
    texts: list[str] = []
    images: list[bytes] = []
    seen_hashes: set[str] = set()

    for page_num in range(min(max_pages, len(doc))):
        page = doc[page_num]

        # Extract text; try utf-8 then fall back to latin-1
        raw = page.get_text()
        try:
            raw.encode("utf-8")
        except UnicodeEncodeError:
            raw = raw.encode("latin-1", errors="replace").decode("utf-8", errors="replace")
        texts.append(raw)

        # Extract images
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue

            img_bytes = base_image["image"]
            img_hash = hashlib.md5(img_bytes).hexdigest()
            if img_hash in seen_hashes:
                continue
            seen_hashes.add(img_hash)

            # Keep only images large enough to plausibly be a map
            try:
                pil_img = Image.open(io.BytesIO(img_bytes))
                w, h = pil_img.size
                if w >= 200 and h >= 200:
                    images.append(img_bytes)
            except Exception:
                continue

    doc.close()
    return "\n".join(texts), images
