import io
import re
from datetime import date as date_type
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from app.schemas.aashto import AASHTOObservation
from app.schemas.compare import VersionChange

# ── normative reference parser ────────────────────────────────────────────────

# JSON-path patterns → (documento, capítulo, sección, título)
_DOTD_REF_MAP: list[tuple[re.Pattern, str, str, str, str]] = [
    # Más específicos primero — evitan que patrones genéricos los capturen antes
    (re.compile(r"broken[- ]?back|tangente.*curvas|curvas.*misma.*direcci", re.I),
     "DOTD Louisiana RDM", "Cap. 4", "Sec. 4.2.1", "Curvas Broken-Back"),
    (re.compile(r"compound.*curve|curva.*compuesta|cambio.*curvatura|relaci[oó]n.*radios", re.I),
     "DOTD Louisiana RDM", "Cap. 4", "Sec. 4.2.1", "Curvas Compuestas"),
    (re.compile(r"peralte.*invert|superelevaci[oó]n.*invert|inverted.*super", re.I),
     "DOTD Louisiana RDM", "Cap. 3", "Sec. 3.3.2", "Superelevación — Peralte Invertido"),
    (re.compile(r"superelevation|peralte|emax", re.I),
     "DOTD Louisiana RDM", "Cap. 3", "Sec. 3.3.2", "Superelevación"),
    (re.compile(r"drenaje|escurrimiento|zona.*sin.*escurr|drainag", re.I),
     "DOTD Louisiana RDM", "Cap. 7", "Sec. 7.1", "Drenaje Superficial"),
    (re.compile(r"cross_slope|pendiente.*transversal|bombeo|cross.*slope", re.I),
     "DOTD Louisiana RDM", "Cap. 4", "Sec. 4.4", "Pendiente Transversal Normal"),
    (re.compile(r"lane_width|ancho.*carril|lane.*width", re.I),
     "DOTD Louisiana RDM", "Cap. 4", "Sec. 4.3.1", "Anchos de Carril"),
    (re.compile(r"shoulder_width|ancho.*hombro|shoulder", re.I),
     "DOTD Louisiana RDM", "Cap. 4", "Sec. 4.3.2", "Anchos de Hombro"),
    (re.compile(r"minimum_grade|pendiente.*m[ií]nima", re.I),
     "DOTD Louisiana RDM", "Cap. 5", "Sec. 5.2", "Pendiente Longitudinal Mínima"),
    (re.compile(r"grade\.max|pendiente.*longitudinal|max.*grade|longitudinal.*grade", re.I),
     "DOTD Louisiana RDM", "Cap. 5", "Sec. 5.2", "Pendiente Longitudinal Máxima"),
    (re.compile(r"stopping_sight|SSD|visibilidad.*parada", re.I),
     "DOTD Louisiana RDM / AASHTO Green Book", "Cap. 3", "Sec. 3.1", "Distancia de Visibilidad de Parada"),
    (re.compile(r"k_value|curva.*vertical|vertical.*curve", re.I),
     "DOTD Louisiana RDM", "Cap. 5", "Sec. 5.3", "Curvas Verticales"),
    (re.compile(r"clear_zone|zona.*libre", re.I),
     "DOTD Louisiana RDM / AASHTO Roadside Design Guide", "Cap. 6", "Sec. 6.2", "Zona Libre Lateral"),
    (re.compile(r"horizontal_alignment|minimum_radius|radio.*m[ií]nimo|curvatura.*horizontal", re.I),
     "DOTD Louisiana RDM", "Cap. 3", "Sec. 3.3", "Alineamiento Horizontal — Radios Mínimos"),
    (re.compile(r"design_speed|velocidad.*dise[ñn]o", re.I),
     "DOTD Louisiana RDM", "Cap. 2", "Sec. 2.3", "Velocidad de Diseño"),
]

# Extrae §X.X.X si el LLM ya lo embebió en normative_value
_RE_SECTION = re.compile(r"[Ss]ec(?:tion|\.)\s*([\d.]+)|§\s*([\d.]+)")


def _parse_normative_ref(obs: AASHTOObservation) -> tuple[str, str, str, str, str]:
    """
    Devuelve (documento, capitulo, seccion, titulo, valor_requerido).
    Busca primero en normative_value por §/Section, luego por JSON-path keywords,
    y cae en un fallback genérico si nada coincide.
    """
    combined = f"{obs.parameter} {obs.normative_value} {obs.observation or ''}"

    # Intentar extraer sección explícita del texto
    sec_match = _RE_SECTION.search(combined)
    explicit_sec = sec_match.group(1) or sec_match.group(2) if sec_match else None

    for pattern, doc, chap, sec, title in _DOTD_REF_MAP:
        if pattern.search(combined):
            if explicit_sec and explicit_sec not in sec:
                sec = f"Sec. {explicit_sec}"
            return doc, chap, sec, title, obs.normative_value
    # fallback
    return (
        "DOTD Louisiana RDM / AASHTO Green Book",
        "—",
        f"Sec. {explicit_sec}" if explicit_sec else "—",
        obs.parameter,
        obs.normative_value,
    )


_SEVERITY_LABEL = {
    "critico":    "CRÍTICO",
    "moderado":   "MODERADO",
    "informativo": "INFORMATIVO",
}
_SEVERITY_COLOR = {
    "critico":    RGBColor(0xC0, 0x00, 0x00),
    "moderado":   RGBColor(0xED, 0x7D, 0x31),
    "informativo": RGBColor(0x2E, 0x75, 0xB6),
}
_SEVERITY_BG = {
    "critico":    RGBColor(0xFF, 0xEB, 0xEB),
    "moderado":   RGBColor(0xFF, 0xF4, 0xE8),
    "informativo": RGBColor(0xEB, 0xF3, 0xFF),
}

# ── palette ──────────────────────────────────────────────────────────────────
_BLUE_DARK  = RGBColor(0x1F, 0x39, 0x64)   # headers / portada
_BLUE_MID   = RGBColor(0x2E, 0x75, 0xB6)   # subtítulos / rayas de tabla
_RED        = RGBColor(0xC0, 0x00, 0x00)   # no cumple / crítico
_GREEN      = RGBColor(0x37, 0x86, 0x10)   # cumple
_ORANGE     = RGBColor(0xED, 0x7D, 0x31)   # moderado
_GRAY_LIGHT = RGBColor(0xD6, 0xDC, 0xE4)   # fila par de tabla
_WHITE      = RGBColor(0xFF, 0xFF, 0xFF)


# ── helpers ───────────────────────────────────────────────────────────────────

def _set_cell_bg(cell, color: RGBColor):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), f"{color[0]:02X}{color[1]:02X}{color[2]:02X}")
    tcPr.append(shd)


def _set_cell_border(cell, **edges):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for edge, attrs in edges.items():
        el = OxmlElement(f"w:{edge}")
        for k, v in attrs.items():
            el.set(qn(f"w:{k}"), v)
        tcBorders.append(el)
    tcPr.append(tcBorders)


def _header_row(table, *labels, bg: RGBColor = _BLUE_DARK):
    row = table.rows[0]
    for i, label in enumerate(labels):
        cell = row.cells[i]
        cell.text = label
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.runs[0]
        run.bold = True
        run.font.color.rgb = _WHITE
        run.font.size = Pt(9)
        _set_cell_bg(cell, bg)


def _data_row(table, values: list[str], even: bool, colors: dict[int, RGBColor] | None = None):
    row = table.add_row()
    for i, val in enumerate(values):
        cell = row.cells[i]
        cell.text = val
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.runs[0]
        run.font.size = Pt(8.5)
        if colors and i in colors:
            run.font.color.rgb = colors[i]
            run.bold = True
        if even:
            _set_cell_bg(cell, _GRAY_LIGHT)


def _add_footer(doc: Document, doc_name: str):
    section = doc.sections[0]
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0]
    p.clear()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    run_left = p.add_run(doc_name + "    ")
    run_left.font.size = Pt(8)
    run_left.font.color.rgb = RGBColor(0x70, 0x70, 0x70)

    # page number field
    fldChar1 = OxmlElement("w:fldChar")
    fldChar1.set(qn("w:fldCharType"), "begin")
    instrText = OxmlElement("w:instrText")
    instrText.text = "PAGE"
    fldChar2 = OxmlElement("w:fldChar")
    fldChar2.set(qn("w:fldCharType"), "end")

    run_page = p.add_run()
    run_page.font.size = Pt(8)
    run_page.font.color.rgb = RGBColor(0x70, 0x70, 0x70)
    run_page._r.append(fldChar1)
    run_page._r.append(instrText)
    run_page._r.append(fldChar2)


def _set_column_widths(table, widths_cm: list[float]):
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            cell.width = Cm(widths_cm[i])


# ── main builder ──────────────────────────────────────────────────────────────

def build_report(
    project_name: str,
    responsible_engineer: str,
    report_date: str,
    observations: list[AASHTOObservation],
    changes: list[VersionChange] | None,
) -> bytes:
    doc = Document()

    # ── page margins ──
    section = doc.sections[0]
    section.top_margin    = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    section.left_margin   = Cm(3)
    section.right_margin  = Cm(2.5)

    # ── default style ──
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    _add_footer(doc, project_name)

    # ──────────────────────────────────────────────────────────────────────────
    # PORTADA
    # ──────────────────────────────────────────────────────────────────────────
    for _ in range(6):
        doc.add_paragraph()

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("INFORME TÉCNICO DE VALIDACIÓN VIAL")
    run.bold = True
    run.font.size = Pt(22)
    run.font.color.rgb = _BLUE_DARK

    doc.add_paragraph()

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run2 = sub.add_run(project_name)
    run2.bold = True
    run2.font.size = Pt(16)
    run2.font.color.rgb = _BLUE_MID

    for _ in range(4):
        doc.add_paragraph()

    def _portada_line(label: str, value: str):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r1 = p.add_run(f"{label}: ")
        r1.bold = True
        r1.font.size = Pt(11)
        r1.font.color.rgb = _BLUE_DARK
        r2 = p.add_run(value)
        r2.font.size = Pt(11)

    _portada_line("Ingeniero Responsable", responsible_engineer)
    _portada_line("Fecha", report_date)
    _portada_line("Normativa Aplicada", "DOTD Louisiana Road Design Manual / AASHTO Green Book")

    doc.add_page_break()

    # ──────────────────────────────────────────────────────────────────────────
    # RESUMEN EJECUTIVO
    # ──────────────────────────────────────────────────────────────────────────
    h1 = doc.add_heading("1. Resumen Ejecutivo", level=1)
    h1.runs[0].font.color.rgb = _BLUE_DARK

    total     = len(observations)
    complies  = sum(1 for o in observations if o.complies)
    no_comply = total - complies

    p = doc.add_paragraph()
    p.add_run("El presente informe analiza el cumplimiento normativo bajo estándar AASHTO "
              f"para el proyecto ").font.size = Pt(10)
    run_proj = p.add_run(f"{project_name}.")
    run_proj.bold = True
    run_proj.font.size = Pt(10)

    doc.add_paragraph()

    # summary table
    tbl = doc.add_table(rows=1, cols=3)
    tbl.style = "Table Grid"
    _header_row(tbl, "Total Observaciones", "Cumplen", "No Cumplen")
    _set_column_widths(tbl, [5.5, 5.5, 5.5])

    row = tbl.add_row()
    for i, (val, color) in enumerate([
        (str(total),     _BLUE_DARK),
        (str(complies),  _GREEN),
        (str(no_comply), _RED),
    ]):
        cell = row.cells[i]
        cell.text = val
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p2 = cell.paragraphs[0]
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p2.runs[0]
        run.bold = True
        run.font.size = Pt(14)
        run.font.color.rgb = color

    if changes:
        critical  = sum(1 for c in changes if c.impact == "crítico")
        moderate  = sum(1 for c in changes if c.impact == "moderado")
        info      = sum(1 for c in changes if c.impact == "informativo")

        doc.add_paragraph()
        p3 = doc.add_paragraph()
        p3.add_run(f"Se identificaron {len(changes)} cambios entre versiones: "
                   f"{critical} críticos, {moderate} moderados y {info} informativos.")

    doc.add_paragraph()

    # ──────────────────────────────────────────────────────────────────────────
    # OBSERVACIONES DOTD / AASHTO
    # ──────────────────────────────────────────────────────────────────────────
    h2 = doc.add_heading("2. Observaciones DOTD / AASHTO", level=1)
    h2.runs[0].font.color.rgb = _BLUE_DARK

    cols_obs = ["Parámetro", "Valor Encontrado", "Valor Normativo", "Cumple", "Observación"]
    widths_obs = [4.5, 3.5, 3.5, 1.8, 5.2]

    tbl_obs = doc.add_table(rows=1, cols=len(cols_obs))
    tbl_obs.style = "Table Grid"
    _header_row(tbl_obs, *cols_obs)
    _set_column_widths(tbl_obs, widths_obs)

    for idx, obs in enumerate(observations):
        check = "✓" if obs.complies else "✗"
        color_map = {3: _GREEN if obs.complies else _RED}
        _data_row(
            tbl_obs,
            [obs.parameter, obs.found_value, obs.normative_value, check, obs.observation or ""],
            even=(idx % 2 == 1),
            colors=color_map,
        )

    doc.add_paragraph()

    # ──────────────────────────────────────────────────────────────────────────
    # DETALLE DE INCUMPLIMIENTOS — REFERENCIAS NORMATIVAS
    # ──────────────────────────────────────────────────────────────────────────
    non_compliant = [o for o in observations if not o.complies]

    if non_compliant:
        h_nc = doc.add_heading("3. Detalle de Incumplimientos — Referencias Normativas", level=1)
        h_nc.runs[0].font.color.rgb = _BLUE_DARK

        intro = doc.add_paragraph()
        intro.add_run(
            f"Se detallan a continuación los {len(non_compliant)} parámetros que no cumplen "
            "con la normativa DOTD Louisiana Road Design Manual. Cada ítem incluye la referencia "
            "exacta de documento, capítulo y sección aplicable."
        ).font.size = Pt(9.5)

        doc.add_paragraph()

        for i, obs in enumerate(non_compliant, start=1):
            sev = obs.severity or "informativo"
            sev_label = _SEVERITY_LABEL.get(sev, sev.upper())
            sev_color = _SEVERITY_COLOR.get(sev, _BLUE_MID)
            sev_bg    = _SEVERITY_BG.get(sev, _GRAY_LIGHT)

            ref_doc, ref_chap, ref_sec, ref_title, ref_value = _parse_normative_ref(obs)

            # Título del ítem
            h_item = doc.add_heading(level=2)
            h_item.clear()
            r_num = h_item.add_run(f"{i}. ")
            r_num.font.color.rgb = _BLUE_MID
            r_num.font.size = Pt(11)
            r_param = h_item.add_run(obs.parameter)
            r_param.font.color.rgb = _BLUE_MID
            r_param.font.size = Pt(11)
            r_badge = h_item.add_run(f"  [{sev_label}]")
            r_badge.font.color.rgb = sev_color
            r_badge.font.size = Pt(9)

            # Bloque "Referencia Normativa" — tabla de 1 celda con fondo coloreado
            ref_tbl = doc.add_table(rows=1, cols=1)
            ref_tbl.style = "Table Grid"
            ref_cell = ref_tbl.rows[0].cells[0]
            ref_cell.width = Cm(15.5)
            _set_cell_bg(ref_cell, sev_bg)

            # Línea 1: etiqueta + documento
            p_ref = ref_cell.paragraphs[0]
            p_ref.paragraph_format.space_before = Pt(4)
            p_ref.paragraph_format.space_after  = Pt(2)
            r_label = p_ref.add_run("Referencia Normativa:  ")
            r_label.bold = True
            r_label.font.size = Pt(9)
            r_label.font.color.rgb = _BLUE_DARK
            r_doc = p_ref.add_run(ref_doc)
            r_doc.font.size = Pt(9)

            # Línea 2: capítulo + sección + título
            p_sec = ref_cell.add_paragraph()
            p_sec.paragraph_format.space_before = Pt(1)
            p_sec.paragraph_format.space_after  = Pt(2)
            r_chap = p_sec.add_run(f"{ref_chap}, {ref_sec} — {ref_title}")
            r_chap.font.size = Pt(9)
            r_chap.bold = True
            r_chap.font.color.rgb = _BLUE_DARK

            # Línea 3: valor requerido
            p_val = ref_cell.add_paragraph()
            p_val.paragraph_format.space_before = Pt(1)
            p_val.paragraph_format.space_after  = Pt(4)
            r_vl = p_val.add_run("Parámetro requerido:  ")
            r_vl.bold = True
            r_vl.font.size = Pt(8.5)
            r_val = p_val.add_run(ref_value)
            r_val.font.size = Pt(8.5)

            # Valor encontrado + observación
            p_found = doc.add_paragraph()
            p_found.paragraph_format.space_before = Pt(3)
            r_fl = p_found.add_run("Valor encontrado:  ")
            r_fl.bold = True
            r_fl.font.size = Pt(9)
            r_fl.font.color.rgb = sev_color
            r_fv = p_found.add_run(obs.found_value)
            r_fv.font.size = Pt(9)

            if obs.observation:
                p_obs = doc.add_paragraph()
                p_obs.paragraph_format.space_before = Pt(2)
                r_ol = p_obs.add_run("Observación:  ")
                r_ol.bold = True
                r_ol.font.size = Pt(9)
                r_ov = p_obs.add_run(obs.observation)
                r_ov.font.size = Pt(9)
                r_ov.font.color.rgb = sev_color

            doc.add_paragraph()

    # ──────────────────────────────────────────────────────────────────────────
    # CAMBIOS ENTRE VERSIONES (opcional)
    # ──────────────────────────────────────────────────────────────────────────
    if changes:
        h3 = doc.add_heading("4. Cambios Entre Versiones", level=1)
        h3.runs[0].font.color.rgb = _BLUE_DARK

        _IMPACT_COLORS = {
            "crítico":     _RED,
            "moderado":    _ORANGE,
            "informativo": _BLUE_MID,
        }
        _CHANGE_LABELS = {
            "modificado": "Modificado",
            "agregado":   "Agregado",
            "eliminado":  "Eliminado",
        }

        cols_chg = ["Ubicación", "Tipo de Cambio", "Descripción", "Impacto"]
        widths_chg = [3.5, 3.0, 8.0, 2.5]

        tbl_chg = doc.add_table(rows=1, cols=len(cols_chg))
        tbl_chg.style = "Table Grid"
        _header_row(tbl_chg, *cols_chg)
        _set_column_widths(tbl_chg, widths_chg)

        for idx, chg in enumerate(changes):
            impact_color = _IMPACT_COLORS.get(chg.impact, _BLUE_MID)
            _data_row(
                tbl_chg,
                [chg.location, _CHANGE_LABELS[chg.change_type], chg.description, chg.impact],
                even=(idx % 2 == 1),
                colors={3: impact_color},
            )

        doc.add_paragraph()

    # ──────────────────────────────────────────────────────────────────────────
    # Serialize
    # ──────────────────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
