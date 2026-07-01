import re
import base64
import pdfplumber
from typing import Optional
from fastapi import UploadFile
import io

# Patrones de title block invertido (texto en espejo del cartel CAD)
_NOISE_LINE = re.compile(
    # Palabras clave del cartel invertidas (orden: más específicas primero)
    r"NOITPIRCSED|NOISIVER|EGNAHC|REDRO|KCEHC|NGISED|"   # DESCRIPTION REVISION CHANGE ORDER CHECK DESIGN
    r"TNEMUCODN|REWOLB|RETTEL|"                            # otros residuales originales
    r"ETAD\b|HSIRAP|TNEMGES|SNALP|LANIF|"                 # DATE PARISH SEGMENT PLANS FINAL
    r"TCEJORP|LORTNOC|NOITCES|ETATS|SEIRES|"              # PROJECT CONTROL SECTION STATE SERIES
    r"TUOYAL|cirtemoeG|CIRTEMOEG|"                         # LAYOUT Geometric
    r"REGNIMLEH|UEISACLAC|YUPUD|ELTTAG|"                  # nombres propios invertidos
    r"TNEMTRAPED|NOITATRO|TNEMPOLEVED|"                    # DEPARTMENT TRANSPORTATION DEVELOPMENT
    r"SRENTRAP|NOISIVID|"                                  # PARTNERS DIVISION
    r"EGDIRB|REVIR|"                                       # BRIDGE RIVER invertidos
    r"\.ON\b|"                                             # "NO." invertido
    r"\b01-I\b|"                                           # "I-10" invertido
    r"\b2\\4\b|"                                           # fragmento de ruta "4\2" invertido
    r"\d{2}:\d{2}:\d{1,2}|"                               # timestamps CAD invertidos (82:41:4)
    r"\b\d{4}/\d+/\d+\b|"                                 # fechas invertidas (6202/9/6)
    r"ngd\.|\.dgn|\.DGN|\.dwg|\.pdf|"                     # extensiones CAD (directas e invertidas)
    r"[A-Z]:\\|\\steehS|\\SGWD|\\derahS|tnemgeS\\|EGANIARD\\|DAOR\\",  # rutas CAD
    re.IGNORECASE,
)


def clean_extracted_text(text: str) -> str:
    """Elimina ruido de title block invertido y colapsa números fragmentados."""
    lines = text.splitlines()
    cleaned = [
        line for line in lines
        if not _NOISE_LINE.search(line) and len(line.strip()) >= 3
    ]
    result = "\n".join(cleaned)

    # Colapsar números fragmentados: "3 7 . 5 3" → "37.53"
    result = re.sub(r'(?<=\d) (?=\d)', '', result)
    result = re.sub(r'(?<=\d) (?=\.)', '', result)
    result = re.sub(r'(?<=\.) (?=\d)', '', result)

    return result


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


def is_text_insufficient(cleaned_text: str, min_length: int = 50) -> bool:
    """Returns True when cleaned text has too little content for LLM extraction.

    Triggers Vision fallback for pages that are pure vector CAD (no text layer)
    or have only a title block with no technical data.
    """
    text = cleaned_text.strip()
    if len(text) < min_length:
        return True
    # If there are no multi-digit numbers the page likely has no measurement data
    if not re.search(r"\d{2,}", text):
        return True
    return False


def should_use_vision(
    page_number: int,
    cleaned_text: str,
    force_vision_pages: "set[int] | None" = None,
) -> bool:
    """Decides whether to use Claude Vision for a page.

    Forced pages bypass the automatic text-sufficiency heuristic — useful for
    pages whose text layer exists but doesn't capture CAD table data (e.g. Cross
    Drain Information tables rendered as vector graphics on pages that also have
    structural IDs and notes extractable as text).
    """
    if force_vision_pages and page_number in force_vision_pages:
        return True
    return is_text_insufficient(cleaned_text)


def render_page_to_base64(pdf_bytes: bytes, page_number: int, dpi: int = 150) -> str:
    """Renders one PDF page (1-indexed) to a base64-encoded PNG string."""
    import fitz  # PyMuPDF — optional dependency
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_number - 1]
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
    img_bytes = pix.tobytes("png")
    doc.close()
    return base64.b64encode(img_bytes).decode("utf-8")


async def extract_text_from_pdf(
    file: UploadFile,
    page_range: Optional[str] = None,
    force_vision_pages: "set[int] | None" = None,
) -> tuple[str, list[int], list[dict]]:
    """Extract text from PDF pages with automatic Vision fallback detection.

    Returns:
        text          — combined cleaned text from pages with sufficient content
        pages_used    — 1-indexed list of all processed pages
        vision_pages  — list of {"page_number": int, "image_b64": str} for pages
                        where text was insufficient and PyMuPDF is available
    """
    try:
        import fitz as _fitz  # noqa: F401
        has_fitz = True
    except ImportError:
        has_fitz = False

    contents = await file.read()
    buffer = io.BytesIO(contents)

    vision_pages: list[dict] = []

    with pdfplumber.open(buffer) as pdf:
        total = len(pdf.pages)
        page_indices = parse_page_range(page_range, total)

        texts: list[str] = []
        for idx in page_indices:
            page_text = pdf.pages[idx].extract_text() or ""
            cleaned = clean_extracted_text(page_text)

            if has_fitz and should_use_vision(idx + 1, cleaned, force_vision_pages):
                image_b64 = render_page_to_base64(contents, idx + 1)
                vision_pages.append({"page_number": idx + 1, "image_b64": image_b64})
                texts.append(f"[PÁGINA {idx + 1}: contenido en imagen — Vision activo]")
            else:
                texts.append(cleaned)

    extracted_text = "\n\n".join(texts)
    pages_used = [i + 1 for i in page_indices]
    return extracted_text, pages_used, vision_pages
