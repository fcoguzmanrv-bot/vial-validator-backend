"""
Clasifica cada página de un PDF de planos viales por tipo de contenido,
usando patrones de palabras clave sobre el texto ya limpio (clean_extracted_text).
Genera un índice cacheado para evitar reprocesar el mismo PDF en cada sesión.
"""

import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

from app.services.pdf_service import clean_extracted_text

_CACHE_DIR = Path(__file__).parent.parent / "cache" / "pdf_index"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Patrones de clasificación por categoría — basados en hallazgos reales del I-10
_CATEGORY_PATTERNS: dict[str, re.Pattern] = {
    "alineamiento_horizontal": re.compile(
        r"CURVE\s*DATA|P\.I\.\s*STA|Δ\s*=|DELTA\s*=|P\.C\.\s*STA|P\.T\.\s*STA",
        re.IGNORECASE,
    ),
    "perfil_longitudinal": re.compile(
        r"P\.V\.I\.|V\.C\.\s|VERTICAL\s*CURVE|ELEV\s*=\s*[\d.]+|GRADE\s*=",
        re.IGNORECASE,
    ),
    "drenaje_cross_drain_info": re.compile(
        r"CROSS\s*DRAIN\s*INFORMATION|OUTLET\s*VELOCITY|DIFFERENTIAL\s*HEAD"
        r"|HEADWATER|TAILWATER|HW/D|TW/D",
        re.IGNORECASE,
    ),
    "drenaje_summary_structures": re.compile(
        # Forward text OR CAD-mirrored text (title block renders reversed)
        r"SUMMARY\s*OF\s*DRAINAGE\s*STRUCTURES|YRAMMUS|SERUTCURTS",
        re.IGNORECASE,
    ),
    "drainage_map": re.compile(
        r"EXISTING\s*DRAINAGE|PROPOSED\s*DRAINAGE\s*STRUCTURES"
        r"|DRAINAGE\s*MAP|DRAINAGE\s*AREA",
        re.IGNORECASE,
    ),
    "seccion_tipica": re.compile(
        r"TYPICAL\s*SECTION",
        re.IGNORECASE,
    ),
    "superelevacion": re.compile(
        r"SUPERELEVATION",
        re.IGNORECASE,
    ),
    "traffic_data": re.compile(
        r"TRAFFIC\s*DATA|A\.D\.T\.|DESIGN\s*SPEED\s*=",
        re.IGNORECASE,
    ),
    "general_notes": re.compile(
        r"GENERAL\s*NOTES",
        re.IGNORECASE,
    ),
}


def _compute_hash(data: bytes) -> str:
    sha256 = hashlib.sha256()
    sha256.update(data)
    return sha256.hexdigest()


def _cache_path(file_hash: str) -> Path:
    return _CACHE_DIR / f"{file_hash}.json"


def _classify_from_buffer(pdf_bytes: bytes, file_hash: str, filename: str) -> dict:
    """Core classification logic — runs over pdf_bytes and writes cache."""
    categories: dict[str, list[int]] = {cat: [] for cat in _CATEGORY_PATTERNS}
    categories["no_clasificada"] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            raw_text = page.extract_text() or ""
            text = clean_extracted_text(raw_text)

            matched = False
            for category, pattern in _CATEGORY_PATTERNS.items():
                if pattern.search(text):
                    categories[category].append(i)
                    matched = True

            if not matched:
                categories["no_clasificada"].append(i)

    result = {
        "file_hash": file_hash,
        "filename": filename,
        "total_pages": total_pages,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
    }

    cache_file = _cache_path(file_hash)
    with cache_file.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def classify_pdf_pages(pdf_path: Path, force_refresh: bool = False) -> dict:
    """Clasifica todas las páginas del PDF por tipo de contenido (disk-based API).

    Usa caché si el archivo ya fue procesado antes (mismo hash SHA-256).
    """
    pdf_bytes = pdf_path.read_bytes()
    file_hash = _compute_hash(pdf_bytes)
    cache_file = _cache_path(file_hash)

    if cache_file.exists() and not force_refresh:
        with cache_file.open(encoding="utf-8") as f:
            return json.load(f)

    return _classify_from_buffer(pdf_bytes, file_hash, pdf_path.name)


def classify_pdf_bytes(pdf_bytes: bytes, filename: str = "upload.pdf") -> dict:
    """Clasifica un PDF dado como bytes (API para uploads de FastAPI).

    Usa caché si el contenido ya fue procesado antes.
    """
    file_hash = _compute_hash(pdf_bytes)
    cache_file = _cache_path(file_hash)

    if cache_file.exists():
        with cache_file.open(encoding="utf-8") as f:
            return json.load(f)

    return _classify_from_buffer(pdf_bytes, file_hash, filename)
