from fastapi import APIRouter, UploadFile, File, Form
from typing import Optional
from app.services.pdf_service import extract_text_from_pdf
from app.providers.factory import get_provider
from app.schemas.aashto import ExtractAndValidateResponse
from app.services.validation_rules import apply_all_rules

router = APIRouter()


@router.post("/", response_model=ExtractAndValidateResponse)
async def extract_and_validate(
    file: UploadFile = File(...),
    page_range: Optional[str] = Form(None),
    functional_class: Optional[str] = Form(None),
    speed_mainline: Optional[str] = Form(None),
    speed_ramps: Optional[str] = Form(None),
    speed_collector: Optional[str] = Form(None),
    speed_loops: Optional[str] = Form(None),
    emax: Optional[str] = Form(None),
    context: Optional[str] = Form(None),
):
    text, pages = await extract_text_from_pdf(file, page_range)
    params = {k: v for k, v in {
        "functional_class": functional_class,
        "speed_mainline": speed_mainline,
        "speed_ramps": speed_ramps,
        "speed_collector": speed_collector,
        "speed_loops": speed_loops,
        "emax": emax,
        "context": context,
    }.items() if v}
    observations = await get_provider().validate(text, params or None)
    observations = apply_all_rules(observations)
    return ExtractAndValidateResponse(
        text=text,
        pages_extracted=pages,
        observations=observations,
    )
