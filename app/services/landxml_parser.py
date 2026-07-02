"""
Parser de archivos LandXML (ISO 19910) para Vial Validator — Fase 2
Extrae parámetros de alineamiento horizontal desde archivos exportados
por InRoads, OpenRoads Designer, Civil 3D, MX Road u otros software viales.

Soporta LandXML 1.0 y 1.2. Detecta unidades automáticamente y convierte a pies.
"""

import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


# Namespaces LandXML más comunes
_NAMESPACES = [
    "http://www.landxml.org/schema/LandXML-1.0",
    "http://www.landxml.org/schema/LandXML-1.1",
    "http://www.landxml.org/schema/LandXML-1.2",
    "",
]

_M_TO_FT = 3.28084


def _find_namespace(root: ET.Element) -> str:
    """Detecta el namespace del archivo LandXML."""
    tag = root.tag
    if tag.startswith("{"):
        return tag[1:tag.index("}")]
    return ""


def _ns(tag: str, namespace: str) -> str:
    """Construye tag con namespace."""
    if namespace:
        return f"{{{namespace}}}{tag}"
    return tag


def _detect_units(root: ET.Element, ns: str) -> str:
    """Detecta si el archivo usa unidades métricas o imperiales."""
    units_el = root.find(_ns("Units", ns))
    if units_el is not None:
        metric = units_el.find(_ns("Metric", ns))
        imperial = units_el.find(_ns("Imperial", ns))
        if metric is not None:
            return "meter"
        if imperial is not None:
            return "foot"
    return "meter"  # default


def _to_feet(value: float, units: str) -> float:
    """Convierte valor a pies si está en metros."""
    if units == "meter":
        return round(value * _M_TO_FT, 4)
    return round(value, 4)


def _rad_to_deg(rad: float) -> float:
    """Convierte radianes a grados."""
    return round(math.degrees(rad), 6)


def _calc_delta(dir_start: float, dir_end: float, rot: str) -> float:
    """
    Calcula ángulo de deflexión Δ en grados desde direcciones en radianes.
    Maneja el cruce de 0/2π correctamente.
    """
    delta = dir_end - dir_start
    # Normalizar a [-π, π]
    while delta > math.pi:
        delta -= 2 * math.pi
    while delta < -math.pi:
        delta += 2 * math.pi
    return round(abs(math.degrees(delta)), 6)


def _parse_coords(text: str) -> list[float] | None:
    """Parsea coordenadas desde texto 'N E Z' o 'N E'."""
    if not text:
        return None
    parts = text.strip().split()
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None


def _parse_line(el: ET.Element, ns: str, units: str, sta_start: float) -> dict:
    """Parsea elemento <Line>."""
    length = float(el.get("length", 0))
    direction = float(el.get("dir", 0))
    sta = float(el.get("staStart", sta_start))

    return {
        "type": "Line",
        "length_ft": _to_feet(length, units),
        "sta_start_ft": _to_feet(sta, units),
        "sta_end_ft": _to_feet(sta + length, units),
        "direction_deg": round(_rad_to_deg(direction), 4),
    }


def _parse_curve(el: ET.Element, ns: str, units: str, sta_start: float) -> dict:
    """Parsea elemento <Curve>."""
    radius = float(el.get("radius", 0))
    length = float(el.get("length", 0))
    chord = float(el.get("chord", 0))
    rot = el.get("rot", "cw")
    dir_start = float(el.get("dirStart", 0))
    dir_end = float(el.get("dirEnd", 0))
    sta = float(el.get("staStart", sta_start))

    delta_deg = _calc_delta(dir_start, dir_end, rot)

    # Extraer coordenadas PI
    pi_el = el.find(_ns("PI", ns))
    pi_coords = None
    if pi_el is not None:
        pi_coords = _parse_coords(pi_el.text)

    return {
        "type": "Curve",
        "radius_ft": _to_feet(radius, units),
        "length_ft": _to_feet(length, units),
        "chord_ft": _to_feet(chord, units),
        "rotation": "RT" if rot == "cw" else "LT",
        "delta_deg": delta_deg,
        "sta_PC_ft": _to_feet(sta, units),
        "sta_PT_ft": _to_feet(sta + length, units),
        "dir_start_deg": _rad_to_deg(dir_start),
        "dir_end_deg": _rad_to_deg(dir_end),
        "PI_coords": pi_coords,
    }


def _parse_spiral(el: ET.Element, ns: str, units: str, sta_start: float) -> dict:
    """Parsea elemento <Spiral>."""
    length = float(el.get("length", 0))
    radius_start_str = el.get("radiusStart", "INF")
    radius_end_str = el.get("radiusEnd", "INF")
    rot = el.get("rot", "cw")
    dir_start = float(el.get("dirStart", 0))
    dir_end = float(el.get("dirEnd", 0))
    sta = float(el.get("staStart", sta_start))
    spi_type = el.get("spiType", "clothoid")
    constant = float(el.get("constant", 0))

    radius_start = None if radius_start_str == "INF" else _to_feet(float(radius_start_str), units)
    radius_end = None if radius_end_str == "INF" else _to_feet(float(radius_end_str), units)

    return {
        "type": "Spiral",
        "length_ft": _to_feet(length, units),
        "sta_start_ft": _to_feet(sta, units),
        "sta_end_ft": _to_feet(sta + length, units),
        "radius_start_ft": radius_start,
        "radius_end_ft": radius_end,
        "rotation": "RT" if rot == "cw" else "LT",
        "dir_start_deg": _rad_to_deg(dir_start),
        "dir_end_deg": _rad_to_deg(dir_end),
        "spiral_type": spi_type,
        "constant": _to_feet(constant, units) if constant else None,
    }


def _parse_alignment(al_el: ET.Element, ns: str, units: str) -> dict:
    """Parsea un elemento <Alignment> completo."""
    name = al_el.get("name", "Sin nombre")
    length = float(al_el.get("length", 0))
    sta_start = float(al_el.get("staStart", 0))
    desc = al_el.get("desc", "")
    state = al_el.get("state", "")

    elements = []
    coord_geom = al_el.find(_ns("CoordGeom", ns))
    if coord_geom is not None:
        current_sta = sta_start
        for child in coord_geom:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "Line":
                el_data = _parse_line(child, ns, units, current_sta)
                elements.append(el_data)
                current_sta += float(child.get("length", 0))
            elif tag == "Curve":
                el_data = _parse_curve(child, ns, units, current_sta)
                elements.append(el_data)
                current_sta += float(child.get("length", 0))
            elif tag == "Spiral":
                el_data = _parse_spiral(child, ns, units, current_sta)
                elements.append(el_data)
                current_sta += float(child.get("length", 0))

    return {
        "name": name,
        "description": desc,
        "state": state,
        "length_ft": _to_feet(length, units),
        "sta_start_ft": _to_feet(sta_start, units),
        "sta_end_ft": _to_feet(sta_start + length, units),
        "elements": elements,
        "summary": {
            "total_elements": len(elements),
            "lines": sum(1 for e in elements if e["type"] == "Line"),
            "curves": sum(1 for e in elements if e["type"] == "Curve"),
            "spirals": sum(1 for e in elements if e["type"] == "Spiral"),
        }
    }


def parse_landxml(file_path: Path | str) -> dict:
    """
    Parsea un archivo LandXML y retorna los parámetros de alineamiento
    en formato estructurado con unidades en pies.

    Args:
        file_path: Ruta al archivo .xml LandXML

    Returns:
        dict con estructura:
        {
            "filename": str,
            "units_original": "meter" | "foot",
            "units_output": "feet",
            "software": str,
            "alignments": [...]
        }
    """
    path = Path(file_path)
    tree = ET.parse(path)
    root = tree.getroot()

    ns = _find_namespace(root)
    units = _detect_units(root, ns)

    # Detectar software de origen
    app_el = root.find(_ns("Application", ns))
    software = ""
    if app_el is not None:
        software = f"{app_el.get('name', '')} v{app_el.get('version', '')}"

    # Parsear todos los alineamientos
    alignments = []
    alignments_container = root.find(_ns("Alignments", ns))
    if alignments_container is not None:
        for al_el in alignments_container.findall(_ns("Alignment", ns)):
            alignments.append(_parse_alignment(al_el, ns, units))

    return {
        "filename": path.name,
        "units_original": units,
        "units_output": "feet",
        "software": software,
        "total_alignments": len(alignments),
        "alignments": alignments,
    }


def extract_curves_for_validation(parsed: dict) -> list[dict]:
    """
    Extrae solo las curvas horizontales del resultado parseado,
    en el formato esperado por las reglas de validación de Vial Validator.

    Returns:
        Lista de dicts con parámetros de curva listos para validar.
    """
    curves = []
    for alignment in parsed["alignments"]:
        for el in alignment["elements"]:
            if el["type"] == "Curve":
                curves.append({
                    "alignment_name": alignment["name"],
                    "radius_ft": el["radius_ft"],
                    "length_ft": el["length_ft"],
                    "delta_deg": el["delta_deg"],
                    "rotation": el["rotation"],
                    "sta_PC_ft": el["sta_PC_ft"],
                    "sta_PT_ft": el["sta_PT_ft"],
                    "PI_coords": el.get("PI_coords"),
                })
    return curves
