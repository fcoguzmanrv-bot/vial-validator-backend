"""
Reglas de validación post-LLM aplicadas de forma determinista sobre la lista
de observaciones extraídas. Estas reglas cubren condiciones que requieren
comparar múltiples parámetros simultáneamente — algo poco fiable si se delega
solo al LLM.
"""

import re
from app.schemas.aashto import AASHTOObservation

# ── Patrones de parámetros ────────────────────────────────────────────────────

_KW_LONG_GRADE = re.compile(
    r"pendiente\s*(longitudinal|long\.?)|longitudinal\s*grade|grade\s*longitudinal",
    re.IGNORECASE,
)
_KW_CROSS_SLOPE = re.compile(
    r"pendiente\s*(transversal|trans\.?|normal)|cross\s*slope|bombeo",
    re.IGNORECASE,
)

# El LLM puede reportar peralte invertido con distintas formulaciones;
# este patrón captura cualquiera de ellas para que Python las normalice.
_KW_INVERTED_SUPER = re.compile(
    r"peralte\s*invert|superelevaci[oó]n\s*invert|inverted\s*super|"
    r"wrong[- ]?way\s*super|super.*direcci[oó]n.*contraria|"
    r"peralte.*contrari|superelevaci[oó]n.*contrari",
    re.IGNORECASE,
)

# Curvas compuestas — el LLM usa este prefijo en `parameter`
_KW_COMPOUND = re.compile(
    r"curva\s*compuesta|compound\s*curve|cambio\s*(brusco\s*de\s*)?curvatura|"
    r"relaci[oó]n\s*de\s*radios|radio\s*ratio",
    re.IGNORECASE,
)

# Broken-back — el LLM usa este prefijo en `parameter`
_KW_BROKEN_BACK = re.compile(
    r"broken[- ]?back|curva[s]?\s*back[- ]?to[- ]?back|"
    r"tangente\s*(corta|insuficiente)\s*(entre\s*curvas?)?|"
    r"curvas?\s*(misma\s*direcci[oó]n|consecutivas?\s*igual)",
    re.IGNORECASE,
)

# Detecta si el contexto es una rampa para aplicar el umbral correcto
_KW_RAMP = re.compile(r"\b(ramp[a]?|ramal|loop)\b", re.IGNORECASE)

# Transición de peralte — el LLM usa este prefijo en `parameter`
_KW_SUPER_TRANSITION = re.compile(
    r"transici[oó]n\s*(de\s*)?peralte|superelevation\s*transition|"
    r"longitud\s*(de\s*)?transici[oó]n|runoff\s*length|tangent\s*runout|"
    r"transition\s*length.*super|super.*transition\s*length",
    re.IGNORECASE,
)

# Extrae parámetros del found_value codificado por el LLM
# Formato esperado: "L=115ft, e=6%, V=65mph, carriles=2, rotacion=centerline"
_RE_TRANS_L     = re.compile(r"\bL\s*=\s*([\d,.]+)\s*ft", re.IGNORECASE)
_RE_TRANS_E     = re.compile(r"\be\s*=\s*([\d,.]+)\s*%", re.IGNORECASE)
_RE_TRANS_V     = re.compile(r"\bV\s*=\s*([\d]+)\s*mph", re.IGNORECASE)
_RE_TRANS_LANES = re.compile(r"carriles?\s*=\s*(\d+)", re.IGNORECASE)
_RE_TRANS_ROT   = re.compile(r"rotaci[oó]n\s*=\s*(centerline|edge|median)", re.IGNORECASE)

# Pequeño ángulo de deflexión — el LLM usa este prefijo en `parameter`
_KW_SMALL_DEFLECTION = re.compile(
    r"peque[ñn]o\s*[aá]ngulo|small\s*deflection|deflection\s*angle|"
    r"[aá]ngulo\s*de\s*deflexi[oó]n|curva.*peque[ñn].*[aá]ngulo|"
    r"deflexi[oó]n\s*(peque[ñn]|insuficiente)|"
    r"longitud.*[aá]ngulo.*deflexi[oó]n|kink.*curve|curve.*kink",
    re.IGNORECASE,
)

# Extrae L y Δ del found_value codificado por el LLM
# Formato esperado: "L=250ft, delta=5deg" o "L=250ft, delta=5°"
_RE_DEFL_L     = re.compile(r"\bL\s*=\s*([\d,.]+)\s*ft", re.IGNORECASE)
_RE_DEFL_DELTA = re.compile(r"\bdelta\s*=\s*([\d,.]+)\s*(?:deg|°|grados?)?", re.IGNORECASE)

# Extrae R1 y R2 del found_value codificado por el LLM
# Formato esperado: "R1=2500ft, R2=800ft, ratio=3.13"
_RE_R1 = re.compile(r"R1\s*=\s*([\d,.]+)\s*ft", re.IGNORECASE)
_RE_R2 = re.compile(r"R2\s*=\s*([\d,.]+)\s*ft", re.IGNORECASE)

# Extrae tangente y velocidad del found_value para broken-back
# Formato esperado: "tangente=650ft, V=65mph, 15V=975ft"
_RE_TANGENT = re.compile(r"tangente\s*=\s*([\d,.]+)\s*ft", re.IGNORECASE)
_RE_SPEED = re.compile(r"V\s*=\s*([\d]+)\s*mph", re.IGNORECASE)

# Valores que representan 0 %
_ZERO_VALUE = re.compile(r"^\s*[+\-]?0+(\.0+)?\s*%?\s*$")


def _is_zero(value: str) -> bool:
    return bool(_ZERO_VALUE.match(value.strip()))


def _find_param(
    observations: list[AASHTOObservation],
    pattern: re.Pattern,
) -> AASHTOObservation | None:
    return next(
        (o for o in observations if pattern.search(o.parameter)),
        None,
    )


def apply_drainage_zero_rule(
    observations: list[AASHTOObservation],
) -> list[AASHTOObservation]:
    """
    Regla de drenaje crítico:
    - Pendiente longitudinal = 0 % Y pendiente transversal = 0 % → CRÍTICO
    - Solo una de las dos = 0 % → MODERADO

    La función AÑADE una nueva observación sintética si detecta la condición.
    También marca `severity` en las observaciones originales involucradas.
    """
    long_obs = _find_param(observations, _KW_LONG_GRADE)
    cross_obs = _find_param(observations, _KW_CROSS_SLOPE)

    long_zero = long_obs is not None and _is_zero(long_obs.found_value)
    cross_zero = cross_obs is not None and _is_zero(cross_obs.found_value)

    synthetic: list[AASHTOObservation] = []

    if long_zero and cross_zero:
        # Marcar observaciones originales
        if long_obs:
            long_obs.severity = "critico"
        if cross_obs:
            cross_obs.severity = "critico"

        synthetic.append(
            AASHTOObservation(
                parameter="Drenaje superficial — pendientes simultáneas en 0%",
                found_value="Pendiente longitudinal = 0.00% y pendiente transversal = 0.00%",
                normative_value=(
                    "DOTD RDM cross_slope.pavement_type.asphalt_concrete.minimum_pct = 1.5% "
                    "y grade.minimum_grade_pct = 0.3%. "
                    "Al menos una pendiente debe ser ≠ 0% para garantizar escurrimiento."
                ),
                complies=False,
                severity="critico",
                observation=(
                    "FALLA DE DISEÑO: Pendiente longitudinal 0% y pendiente transversal 0% "
                    "simultáneas crean una zona sin escurrimiento. El agua no tiene dirección "
                    "de drenaje en ningún plano. Requiere rediseño inmediato o solución de "
                    "drenaje forzado documentada."
                ),
            )
        )

    elif long_zero and not cross_zero:
        if long_obs:
            long_obs.severity = "moderado"

        synthetic.append(
            AASHTOObservation(
                parameter="Drenaje superficial — pendiente longitudinal en 0%",
                found_value="Pendiente longitudinal = 0.00%",
                normative_value="DOTD RDM grade.minimum_grade_pct = 0.3%",
                complies=False,
                severity="moderado",
                observation=(
                    "Pendiente longitudinal = 0% con pendiente transversal ≠ 0%. "
                    "El escurrimiento depende exclusivamente del bombeo transversal. "
                    "Verificar capacidad de drenaje longitudinal y diseño de cunetas."
                ),
            )
        )

    elif cross_zero and not long_zero:
        if cross_obs:
            cross_obs.severity = "moderado"

        synthetic.append(
            AASHTOObservation(
                parameter="Drenaje superficial — pendiente transversal en 0%",
                found_value="Pendiente transversal = 0.00%",
                normative_value=(
                    "DOTD RDM cross_slope.pavement_type.asphalt_concrete.minimum_pct = 1.5%"
                ),
                complies=False,
                severity="moderado",
                observation=(
                    "Pendiente transversal = 0% con pendiente longitudinal ≠ 0%. "
                    "El escurrimiento transversal es nulo; el agua corre solo longitudinalmente. "
                    "Verificar acumulación lateral y capacidad de la cuneta."
                ),
            )
        )

    return observations + synthetic


_INVERTED_SUPER_MSG = (
    "PERALTE INVERTIDO: Superelevación en dirección contraria a la curva. "
    "La fuerza centrífuga no está contrarrestada — riesgo de accidente. "
    "Corrección inmediata requerida."
)

_INVERTED_SUPER_NORM = (
    "DOTD RDM superelevation: la calzada debe inclinarse hacia el interior de la curva. "
    "Curva RT → inclinación hacia la derecha. "
    "Curva LT → inclinación hacia la izquierda. "
    "Ref: AASHTO Green Book §3.3 / DOTD RDM horizontal_alignment."
)


def apply_inverted_superelevation_rule(
    observations: list[AASHTOObservation],
) -> list[AASHTOObservation]:
    """
    Normaliza cualquier observación de peralte invertido que el LLM haya reportado:
    - Fuerza severity = "critico" y complies = False.
    - Sustituye el mensaje de observación por el texto estándar si está ausente
      o si el LLM usó una formulación distinta.
    - Si el LLM no detectó ninguna pero dejó señales en found_value o observation
      (p. ej. "izquierda" + "RT"), no se duplica — esa responsabilidad queda en
      el prompt; aquí solo normalizamos lo ya detectado.
    """
    changed = False
    for obs in observations:
        if _KW_INVERTED_SUPER.search(obs.parameter) or (
            obs.observation and _KW_INVERTED_SUPER.search(obs.observation)
        ):
            obs.complies = False
            obs.severity = "critico"
            obs.normative_value = _INVERTED_SUPER_NORM
            # Preservar contexto específico del LLM (ramp id, valores) pero anteponer
            # el mensaje estándar si aún no está presente.
            if _INVERTED_SUPER_MSG not in (obs.observation or ""):
                original_detail = obs.observation or ""
                obs.observation = (
                    f"{_INVERTED_SUPER_MSG}"
                    + (f" — {original_detail}" if original_detail else "")
                )
            changed = True

    return observations


def _parse_float(text: str) -> float | None:
    """Convierte '2,500' o '2500' a float; devuelve None si falla."""
    try:
        return float(text.replace(",", ""))
    except (ValueError, AttributeError):
        return None


# ── Umbrales curvas compuestas (DOTD RDM Section 4.2.1) ──────────────────────
_COMPOUND_RATIO_MAIN_WARN  = 1.5   # carretera principal → moderado
_COMPOUND_RATIO_RAMP_WARN  = 2.0   # rampa               → moderado
_COMPOUND_RATIO_HARD_CRIT  = 3.0   # cualquier caso      → critico


def apply_compound_curve_rule(
    observations: list[AASHTOObservation],
) -> list[AASHTOObservation]:
    """
    Normaliza observaciones de curvas compuestas que el LLM haya detectado.
    Extrae R1/R2 del found_value y recalcula la severidad de forma determinista.

    Umbrales (DOTD RDM §4.2.1):
      R1/R2 > 3.0 (cualquier caso)  → critico
      R1/R2 > 2.0 en rampas         → moderado
      R1/R2 > 1.5 en vía principal  → moderado
    """
    for obs in observations:
        if not _KW_COMPOUND.search(obs.parameter):
            continue

        obs.complies = False

        # Intentar extraer R1 y R2 para verificación numérica independiente
        m_r1 = _RE_R1.search(obs.found_value)
        m_r2 = _RE_R2.search(obs.found_value)
        r1 = _parse_float(m_r1.group(1)) if m_r1 else None
        r2 = _parse_float(m_r2.group(1)) if m_r2 else None

        is_ramp = bool(_KW_RAMP.search(obs.parameter))
        warn_threshold = _COMPOUND_RATIO_RAMP_WARN if is_ramp else _COMPOUND_RATIO_MAIN_WARN

        if r1 is not None and r2 is not None and r2 > 0:
            ratio = round(r1 / r2, 2)
            if ratio >= _COMPOUND_RATIO_HARD_CRIT:
                severity = "critico"
            elif ratio > warn_threshold:
                severity = "moderado"
            else:
                # El LLM lo marcó como problema pero el ratio no supera umbral;
                # confiar en el LLM pero bajar a informativo.
                severity = "informativo"

            obs.severity = severity
            obs.normative_value = (
                f"DOTD RDM §4.2.1 horizontal_alignment — "
                f"ratio máximo {'2.0:1 (rampas)' if is_ramp else '1.5:1 (vía principal)'}; "
                f"3.0:1 en cualquier caso."
            )
            obs.observation = (
                f"CAMBIO BRUSCO DE CURVATURA: Relación de radios R1/R2 = {ratio} "
                f"supera el máximo de {warn_threshold}:1 "
                f"(DOTD RDM Section 4.2.1). "
                f"Riesgo de velocidad inconsistente para el conductor."
                + (f" — {obs.observation}" if obs.observation else "")
            )
        else:
            # Sin datos numéricos: conservar lo que reportó el LLM pero garantizar
            # severidad mínima.
            if obs.severity not in ("critico", "moderado"):
                obs.severity = "moderado"
            obs.normative_value = obs.normative_value or (
                "DOTD RDM §4.2.1: ratio máximo 1.5:1 (vía principal) / "
                "2.0:1 (rampas) / 3.0:1 (límite absoluto)."
            )

    return observations


# ── Umbrales broken-back (DOTD RDM Section 4.2.1) ────────────────────────────
_BROKEN_BACK_FACTOR = 15  # tangente mínima = 15 × V (mph) en ft


def apply_broken_back_rule(
    observations: list[AASHTOObservation],
) -> list[AASHTOObservation]:
    """
    Normaliza observaciones de curvas broken-back que el LLM haya detectado.
    Extrae tangente y velocidad del found_value y recalcula la severidad.

    Umbral (DOTD RDM §4.2.1):
      tangente < 15 × V_mph → moderado
      (La condición ya implica incumplimiento; no existe nivel crítico separado.)
    """
    for obs in observations:
        if not _KW_BROKEN_BACK.search(obs.parameter):
            continue

        obs.complies = False

        m_t = _RE_TANGENT.search(obs.found_value)
        m_v = _RE_SPEED.search(obs.found_value)
        tangent = _parse_float(m_t.group(1)) if m_t else None
        speed   = _parse_float(m_v.group(1)) if m_v else None

        if tangent is not None and speed is not None:
            min_tangent = _BROKEN_BACK_FACTOR * speed
            obs.severity = "moderado"
            obs.normative_value = (
                f"DOTD RDM §4.2.1: tangente mínima entre curvas en la misma dirección "
                f"= 15 × V = 15 × {int(speed)} mph = {int(min_tangent)} ft."
            )
            obs.observation = (
                f"CURVA BROKEN-BACK: Tangente entre curvas en la misma dirección "
                f"= {int(tangent)} ft, menor a 15v = {int(min_tangent)} ft "
                f"(DOTD RDM Section 4.2.1). "
                f"Apariencia visual deficiente y operación errática."
                + (f" — {obs.observation}" if obs.observation else "")
            )
        else:
            if obs.severity not in ("critico", "moderado"):
                obs.severity = "moderado"
            obs.normative_value = obs.normative_value or (
                "DOTD RDM §4.2.1: tangente mínima = 15 × V (mph) ft entre curvas "
                "consecutivas en la misma dirección."
            )

    return observations


# ── Denominadores de gradiente relativo máximo (DOTD RDM Sec. 4.6.3) ─────────
# Fuente: Table 3-15 AASHTO Green Book citada en DOTD RDM April 2022, p. 4-19
# Para velocidades no listadas en el manual se interpola linealmente.
_TRANS_GRADIENT_DENOM: dict[int, int] = {
    30: 152,
    40: 172,
    45: 185,
    50: 200,
    55: 211,   # interpolado entre 50 y 60
    60: 222,
    65: 236,   # interpolado entre 60 y 70
    70: 250,
    75: 250,   # conservador (manual no lista; usar 70 mph)
    80: 250,   # conservador
}

# Lane factors (DOTD RDM Sec. 4.6.3, Table 3-16 AASHTO)
_LANE_FACTOR_CL:   dict[int, float] = {2: 1.0, 3: 1.2, 4: 1.5, 5: 1.7, 6: 2.0}
_LANE_FACTOR_EDGE: dict[int, float] = {2: 1.5, 3: 2.0, 4: 2.5, 5: 3.0, 6: 3.5}

_DEFAULT_LANE_WIDTH  = 12    # ft
_NORMAL_CROWN        = 0.025 # 2.5 % (DOTD usa 2.5 % de corona normal)


def _calc_super_transition(
    e_pct: float,
    speed_mph: int,
    lanes: int,
    rotation: str,  # "centerline" | "edge" | "median"
) -> float:
    """
    Calcula longitud mínima de transición de peralte (ft) según DOTD RDM Sec. 4.6.3.

        L = |Δe| × W × lane_factor / (1 / denom)
          = |Δe| × W × lane_factor × denom

    Δe = cambio desde corona normal (2.5 %) hasta peralte pleno.
    """
    denom = _TRANS_GRADIENT_DENOM.get(speed_mph, 250)

    if rotation == "edge":
        lf = _LANE_FACTOR_EDGE.get(lanes, 1.5)
    else:  # centerline o median → usar centerline como conservador
        lf = _LANE_FACTOR_CL.get(lanes, 1.0)

    slope_change = abs(e_pct / 100 - (-_NORMAL_CROWN))  # ft/ft
    length = slope_change * _DEFAULT_LANE_WIDTH * lf * denom

    # Redondear hacia arriba al múltiplo de 10 más cercano
    import math
    return math.ceil(length / 10) * 10


def apply_superelevation_transition_rule(
    observations: list[AASHTOObservation],
) -> list[AASHTOObservation]:
    """
    Valida longitudes de transición de peralte según DOTD RDM Sec. 4.6.3.

    El LLM detecta transiciones e incluye en found_value:
        "L=115ft, e=6%, V=65mph, carriles=2, rotacion=centerline"

    Si faltan datos, el sistema aplica supuestos conservadores documentados:
        - Vía principal: 4 carriles, rotación centerline
        - Rampa: 2 carriles, rotación edge
        - W = 12 ft (estándar DOTD)

    La observación siempre indica los supuestos usados para que el ingeniero
    pueda verificar contra la sección típica real.
    """
    for obs in observations:
        if not _KW_SUPER_TRANSITION.search(obs.parameter):
            continue

        obs.complies = False

        # Extraer parámetros del found_value
        m_l     = _RE_TRANS_L.search(obs.found_value)
        m_e     = _RE_TRANS_E.search(obs.found_value)
        m_v     = _RE_TRANS_V.search(obs.found_value)
        m_lanes = _RE_TRANS_LANES.search(obs.found_value)
        m_rot   = _RE_TRANS_ROT.search(obs.found_value)

        l_indicated = _parse_float(m_l.group(1)) if m_l else None
        e_pct       = _parse_float(m_e.group(1)) if m_e else None
        speed       = int(m_v.group(1))           if m_v else None
        lanes       = int(m_lanes.group(1))        if m_lanes else None
        rotation    = m_rot.group(1).lower()       if m_rot else None

        is_ramp = bool(_KW_RAMP.search(obs.parameter))

        # Supuestos conservadores cuando faltan datos
        assumed: list[str] = []
        if speed is None:
            speed = 65
            assumed.append("V=65mph (supuesto — velocidad de diseño no indicada)")
        if e_pct is None:
            e_pct = 6.0
            assumed.append("e=6% (supuesto — peralte máx. freeway urbano DOTD)")
        if lanes is None:
            lanes = 2 if is_ramp else 4
            assumed.append(f"carriles={lanes} (supuesto por {'rampa' if is_ramp else 'vía principal'})")
        if rotation is None:
            rotation = "edge" if is_ramp else "centerline"
            assumed.append(f"rotacion={rotation} (supuesto conservador)")

        l_min = _calc_super_transition(e_pct, speed, lanes, rotation)

        assumption_note = (
            " Supuestos aplicados (verificar sección típica): "
            + "; ".join(assumed) + "."
            if assumed else ""
        )

        obs.normative_value = (
            f"DOTD RDM Sec. 4.6.3 — L_min = {l_min} ft "
            f"(e={e_pct}%, V={speed}mph, {lanes} carriles, "
            f"rotación={rotation}, W=12ft)."
        )

        if l_indicated is not None:
            deficiency_pct = round((l_min - l_indicated) / l_min * 100, 1)
            obs.severity = "critico" if deficiency_pct > 15 else "moderado"
            obs.observation = (
                f"TRANSICIÓN DE PERALTE INSUFICIENTE: Longitud indicada {l_indicated:.0f} ft "
                f"< mínimo calculado {l_min} ft (deficiencia {deficiency_pct}%). "
                f"La calzada cambia de pendiente transversal demasiado abruptamente — "
                f"riesgo de acumulación de agua y pérdida de tracción en la transición. "
                f"DOTD RDM Sec. 4.6.3.{assumption_note}"
            )
        else:
            # El LLM detectó el problema pero no entregó L numérica
            obs.severity = obs.severity if obs.severity in ("critico", "moderado") else "moderado"
            obs.observation = (
                f"TRANSICIÓN DE PERALTE: Longitud de transición indicada no determinada. "
                f"Longitud mínima calculada: {l_min} ft "
                f"(e={e_pct}%, V={speed}mph, {lanes} carriles, rotación={rotation}). "
                f"Verificar longitud en plano de superelevación. "
                f"DOTD RDM Sec. 4.6.3.{assumption_note}"
            )

    return observations


# ── Pequeño ángulo de deflexión (DOTD RDM Section 4.2.1) ─────────────────────
# L_min = 1 000 - 100 × Δ (ft), aplicable para Δ < 10°.
# Curvas más cortas que este mínimo producen el efecto visual de "kink"
# (quiebre aparente en la alineación) que puede sorprender al conductor.
_SMALL_DEFL_MAX_ANGLE = 5.0    # ángulos ≥ 5° → la restricción no aplica (DOTD RDM Sec. 4.2.1)


def apply_small_deflection_angle_rule(
    observations: list[AASHTOObservation],
) -> list[AASHTOObservation]:
    """
    Valida longitudes mínimas de curvas con pequeño ángulo de deflexión
    según DOTD RDM Sec. 4.2.1.

    Fórmula:  L_min = 1 000 - 100 × Δ  (ft),  válido para Δ < 10°.

    El LLM detecta la condición e incluye en found_value:
        "L=250ft, delta=5deg"

    Si Δ no está disponible, se aplica el supuesto conservador Δ=2° (L_min=800 ft).
    Si Δ ≥ 10°, la restricción no aplica y la observación se marca informativo.
    """
    for obs in observations:
        if not _KW_SMALL_DEFLECTION.search(obs.parameter):
            continue

        obs.complies = False

        m_l = _RE_DEFL_L.search(obs.found_value)
        m_d = _RE_DEFL_DELTA.search(obs.found_value)

        l_indicated = _parse_float(m_l.group(1)) if m_l else None
        delta       = _parse_float(m_d.group(1)) if m_d else None

        assumed: list[str] = []
        if delta is None:
            delta = 2.0
            assumed.append("delta=2° (supuesto conservador — ángulo no indicado)")

        if delta >= _SMALL_DEFL_MAX_ANGLE:
            obs.severity = obs.severity if obs.severity in ("critico", "moderado") else "informativo"
            obs.normative_value = (
                "DOTD RDM Sec. 4.2.1: restricción L_min = 1000 - 100×Δ aplica solo "
                f"para Δ < 10° (ángulo reportado: Δ={delta}°)."
            )
            continue

        l_min = round(1000 - 100 * delta)

        assumption_note = (
            " Supuestos aplicados: " + "; ".join(assumed) + "."
            if assumed else ""
        )

        obs.normative_value = (
            f"DOTD RDM Sec. 4.2.1 — L_min = 1000 - 100×Δ = "
            f"1000 - 100×{delta}° = {l_min} ft."
        )

        obs.severity = "moderado"

        if l_indicated is not None:
            deficiency_pct = round((l_min - l_indicated) / l_min * 100, 1)
            obs.observation = (
                f"CURVA CON PEQUEÑO ÁNGULO DE DEFLEXIÓN: Longitud indicada {l_indicated:.0f} ft "
                f"< mínimo requerido {l_min} ft para Δ={delta}° "
                f"(deficiencia {deficiency_pct}%). "
                f"Una curva corta con ángulo pequeño crea el efecto visual de 'kink' "
                f"(quiebre aparente en la alineación) que puede sorprender al conductor. "
                f"DOTD RDM Sec. 4.2.1.{assumption_note}"
            )
        else:
            obs.observation = (
                f"CURVA CON PEQUEÑO ÁNGULO DE DEFLEXIÓN (Δ={delta}°): "
                f"Longitud mínima requerida: {l_min} ft. "
                f"Verificar longitud de curva en el plano horizontal. "
                f"DOTD RDM Sec. 4.2.1.{assumption_note}"
            )

    return observations


def apply_all_rules(
    observations: list[AASHTOObservation],
) -> list[AASHTOObservation]:
    """Punto de entrada: aplica todas las reglas en orden."""
    observations = apply_drainage_zero_rule(observations)
    observations = apply_inverted_superelevation_rule(observations)
    observations = apply_compound_curve_rule(observations)
    observations = apply_broken_back_rule(observations)
    observations = apply_superelevation_transition_rule(observations)
    observations = apply_small_deflection_angle_rule(observations)
    return observations
