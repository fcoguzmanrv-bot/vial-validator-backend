from pydantic import BaseModel
from typing import Optional


class AASHTOObservation(BaseModel):
    parameter: str
    found_value: str
    normative_value: str
    complies: bool
    observation: Optional[str] = None


class ValidationRequest(BaseModel):
    text: str


class ValidationResponse(BaseModel):
    observations: list[AASHTOObservation]


class ExtractResponse(BaseModel):
    text: str
    pages_extracted: list[int]


class ExtractAndValidateResponse(BaseModel):
    text: str
    pages_extracted: list[int]
    observations: list[AASHTOObservation]
