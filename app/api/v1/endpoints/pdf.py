from fastapi import APIRouter, UploadFile, File, Form
from typing import Optional
from app.services.pdf_service import extract_text_from_pdf
from app.schemas.aashto import ExtractResponse

router = APIRouter()


@router.post("/extract", response_model=ExtractResponse)
async def extract_pdf(
    file: UploadFile = File(...),
    page_range: Optional[str] = Form(None),
):
    text, pages = await extract_text_from_pdf(file, page_range)
    return ExtractResponse(text=text, pages_extracted=pages)
