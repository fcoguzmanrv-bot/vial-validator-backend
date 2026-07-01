from fastapi import APIRouter, File, UploadFile

from app.services.pdf_classifier import classify_pdf_bytes

router = APIRouter()


@router.post("/")
async def classify_pdf(file: UploadFile = File(...)) -> dict:
    pdf_bytes = await file.read()
    return classify_pdf_bytes(pdf_bytes, file.filename or "upload.pdf")
