from fastapi import APIRouter, UploadFile, File, Form
from typing import Optional
from app.services.pdf_service import extract_text_from_pdf
from app.providers.factory import get_provider
from app.schemas.aashto import ExtractAndValidateResponse
from app.services.validation_rules import apply_all_rules

router = APIRouter()


def _parse_force_vision(raw: Optional[str]) -> "set[int]":
    """Parses '128' or '128,130' or '128-130' into a set of 1-indexed page numbers."""
    if not raw or not raw.strip():
        return set()
    result: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            result.update(range(int(a), int(b) + 1))
        elif part.isdigit():
            result.add(int(part))
    return result


@router.post("/", response_model=ExtractAndValidateResponse)
async def extract_and_validate(
    file: UploadFile = File(...),
    page_range: Optional[str] = Form(None),
    force_vision_pages: Optional[str] = Form(None),
    functional_class: Optional[str] = Form(None),
    speed_mainline: Optional[str] = Form(None),
    speed_ramps: Optional[str] = Form(None),
    speed_collector: Optional[str] = Form(None),
    speed_loops: Optional[str] = Form(None),
    emax: Optional[str] = Form(None),
    context: Optional[str] = Form(None),
):
    forced = _parse_force_vision(force_vision_pages)
    text, pages, vision_pages = await extract_text_from_pdf(file, page_range, forced or None)
    params = {k: v for k, v in {
        "functional_class": functional_class,
        "speed_mainline": speed_mainline,
        "speed_ramps": speed_ramps,
        "speed_collector": speed_collector,
        "speed_loops": speed_loops,
        "emax": emax,
        "context": context,
    }.items() if v}

    provider = get_provider()
    observations = await provider.validate(text, params or None)

    if vision_pages:
        vision_obs = await provider.validate_vision_pages(vision_pages, params or None)
        observations.extend(vision_obs)

    observations = apply_all_rules(observations)
    return ExtractAndValidateResponse(
        text=text,
        pages_extracted=pages,
        observations=observations,
    )
