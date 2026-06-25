from fastapi import APIRouter, UploadFile, File, Form
from typing import Optional
from app.services.pdf_service import extract_text_from_pdf
from app.providers.compare_provider import CompareProvider
from app.schemas.compare import CompareVersionsResponse

router = APIRouter()


@router.post("/", response_model=CompareVersionsResponse)
async def compare_versions(
    pdf_v1: UploadFile = File(...),
    pdf_v2: UploadFile = File(...),
    page_range: Optional[str] = Form(None),
):
    text_v1, _ = await extract_text_from_pdf(pdf_v1, page_range)
    text_v2, _ = await extract_text_from_pdf(pdf_v2, page_range)

    changes = await CompareProvider().compare(text_v1, text_v2)
    return CompareVersionsResponse(changes=changes)
