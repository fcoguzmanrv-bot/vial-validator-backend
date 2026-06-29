import re
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
            texts.append(clean_extracted_text(page_text))

    extracted_text = "\n\n".join(texts)
    pages_used = [i + 1 for i in page_indices]
    return extracted_text, pages_used
