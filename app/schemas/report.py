from pydantic import BaseModel
from typing import Optional
from app.schemas.aashto import AASHTOObservation
from app.schemas.compare import VersionChange


class ReportRequest(BaseModel):
    project_name: str
    responsible_engineer: str          # kept for backward compat; alias for engineer
    contract_number: Optional[str] = None
    reviewing_firm: Optional[str] = None
    date: Optional[str] = None         # ISO YYYY-MM-DD; defaults to today if omitted
    observations: list[AASHTOObservation]
    changes: Optional[list[VersionChange]] = None
    page_range: Optional[str] = None   # e.g. "138-144"
    pdf_filename: Optional[str] = None # original filename shown in portada
