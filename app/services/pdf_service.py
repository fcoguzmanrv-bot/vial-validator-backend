import pdfplumber
from typing import Optional
from fastapi import UploadFile
import io


def parse_page_range(page_range: Optional[str], total_pages: int) -> list[int]:
    if not page_range:
        return list(range(total_pages))

    pages = set()
    for part in page_range.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            pages.update(range(int(start) - 1, int(end)))
        else:
            pages.add(int(part) - 1)

    return sorted(p for p in pages if 0 <= p < total_pages)


async def extract_text_from_pdf(
    file: UploadFile,
    page_range: Optional[str] = None,
) -> tuple[str, list[int]]:
    contents = await file.read()
    buffer = io.BytesIO(contents)

    with pdfplumber.open(buffer) as pdf:
        total = len(pdf.pages)
        page_indices = parse_page_range(page_range, total)

        texts = []
        for idx in page_indices:
            page_text = pdf.pages[idx].extract_text() or ""
            texts.append(page_text)

    extracted_text = "\n\n".join(texts)
    pages_used = [i + 1 for i in page_indices]
    return extracted_text, pages_used
