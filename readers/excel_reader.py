from openpyxl import load_workbook


def extract_text_and_images(xlsx_path: str, max_pages: int = 2) -> tuple[str, list[bytes]]:
    """
    Extract all cell text from an Excel file.
    max_pages is ignored (Excel has no page concept).
    Image extraction from Excel is not supported; returns empty list.
    """
    wb = load_workbook(xlsx_path, data_only=True, read_only=True)
    texts: list[str] = []

    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            for cell_val in row:
                if cell_val is not None:
                    val = str(cell_val).strip()
                    if val:
                        texts.append(val)

    wb.close()
    return "\n".join(texts), []
