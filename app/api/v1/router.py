from fastapi import APIRouter
from app.api.v1.endpoints import pdf, validate, extract_and_validate, compare_versions, generate_report

api_router = APIRouter()

api_router.include_router(pdf.router,                  prefix="/pdf",                  tags=["PDF"])
api_router.include_router(validate.router,             prefix="/validate",             tags=["Validate"])
api_router.include_router(extract_and_validate.router, prefix="/extract-and-validate", tags=["Extract & Validate"])
api_router.include_router(compare_versions.router,     prefix="/compare-versions",     tags=["Compare Versions"])
api_router.include_router(generate_report.router,      prefix="/generate-report",      tags=["Generate Report"])
