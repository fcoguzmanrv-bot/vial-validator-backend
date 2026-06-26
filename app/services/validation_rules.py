"""
Reglas de validación post-LLM aplicadas de forma determinista sobre la lista
de observaciones extraídas. Estas reglas cubren condiciones que requieren
comparar múltiples parámetros simultáneamente — algo poco fiable si se delega
solo al LLM.
"""

import re
from app.schemas.aashto import AASHTOObservation

# Palabras clave que identifican cada familia de parámetro en el campo `parameter`
_KW_LONG_GRADE = re.compile(
    r"pendiente\s*(longitudinal|long\.?)|longitudinal\s*grade|grade\s*longitudinal",
    re.IGNORECASE,
)
_KW_CROSS_SLOPE = re.compile(
    r"pendiente\s*(transversal|trans\.?|normal)|cross\s*slope|bombeo",
    re.IGNORECASE,
)

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


def apply_all_rules(
    observations: list[AASHTOObservation],
) -> list[AASHTOObservation]:
    """Punto de entrada: aplica todas las reglas en orden."""
    observations = apply_drainage_zero_rule(observations)
    return observations
