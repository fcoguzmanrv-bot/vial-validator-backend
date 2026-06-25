from datetime import date
from fastapi import APIRouter
from fastapi.responses import Response
from app.schemas.report import ReportRequest
from app.services.report_service import build_report

router = APIRouter()


@router.post("/")
async def generate_report(body: ReportRequest):
    report_date = body.date or date.today().isoformat()

    docx_bytes = build_report(
        project_name=body.project_name,
        responsible_engineer=body.responsible_engineer,
        report_date=report_date,
        observations=body.observations,
        changes=body.changes,
    )

    filename = body.project_name.replace(" ", "_") + f"_{report_date}.docx"

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
