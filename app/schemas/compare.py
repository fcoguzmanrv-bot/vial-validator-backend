from pydantic import BaseModel
from typing import Literal


class VersionChange(BaseModel):
    location: str
    change_type: Literal["modificado", "agregado", "eliminado"]
    description: str
    impact: Literal["crítico", "moderado", "informativo"]


class CompareVersionsResponse(BaseModel):
    changes: list[VersionChange]
