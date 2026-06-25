from pydantic import BaseModel
from typing import Optional
from app.schemas.aashto import AASHTOObservation
from app.schemas.compare import VersionChange


class ReportRequest(BaseModel):
    project_name: str
    responsible_engineer: str
    date: Optional[str] = None  # ISO format YYYY-MM-DD; defaults to today if omitted
    observations: list[AASHTOObservation]
    changes: Optional[list[VersionChange]] = None
