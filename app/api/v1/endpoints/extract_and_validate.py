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
):
    text, pages = await extract_text_from_pdf(file, page_range)
    observations = await get_provider().validate(text)
    observations = apply_all_rules(observations)
    return ExtractAndValidateResponse(
        text=text,
        pages_extracted=pages,
        observations=observations,
    )
