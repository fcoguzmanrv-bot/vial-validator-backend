from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
import tempfile

from app.services.landxml_parser import parse_landxml, extract_curves_for_validation

router = APIRouter()


@router.post("/parse-landxml/")
async def parse_landxml_file(file: UploadFile = File(...)):
    """
    Parsea un archivo LandXML y retorna los parámetros de alineamiento
    en formato estructurado con unidades en pies.
    """
    if not file.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="El archivo debe ser .xml (LandXML)")

    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        result = parse_landxml(tmp_path)
        result["curves_for_validation"] = extract_curves_for_validation(result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al parsear LandXML: {str(e)}")
    finally:
        tmp_path.unlink(missing_ok=True)
