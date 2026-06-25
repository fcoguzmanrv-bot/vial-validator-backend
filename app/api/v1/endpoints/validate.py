from fastapi import APIRouter
from app.schemas.aashto import ValidationRequest, ValidationResponse
from app.providers.factory import get_provider

router = APIRouter()


@router.post("/", response_model=ValidationResponse)
async def validate_text(body: ValidationRequest):
    provider = get_provider()
    observations = await provider.validate(body.text)
    return ValidationResponse(observations=observations)
