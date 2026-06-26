import json
from pathlib import Path

_DOTD_PARAMS_PATH = Path(__file__).parent.parent / "data" / "dotd_parameters.json"

with _DOTD_PARAMS_PATH.open(encoding="utf-8") as _f:
    _DOTD_PARAMS: dict = json.load(_f)

# Compact JSON embedded in the prompt (no indent to save tokens)
_DOTD_PARAMS_JSON = json.dumps(_DOTD_PARAMS, ensure_ascii=False)

SYSTEM_PROMPT = f"""Eres un experto en diseño geométrico de autopistas y normas del \
DOTD Louisiana Road Design Manual (Louisiana Department of Transportation and Development).

La siguiente sección contiene los parámetros normativos de referencia en formato JSON.
Úsalos como base exclusiva para la validación; NO uses valores AASHTO genéricos \
a menos que el JSON los referencie explícitamente.

<dotd_parameters>
{_DOTD_PARAMS_JSON}
</dotd_parameters>

Analiza el texto extraído del plano o informe vial y extrae todas las observaciones \
de cumplimiento normativo. Para cada parámetro geométrico encontrado (velocidad de \
diseño, radio de curvatura horizontal, superelevación, ancho de carril, ancho de \
hombro, pendiente longitudinal, distancia de visibilidad de parada, pendiente \
transversal) indica:

- parameter: nombre del parámetro evaluado
- found_value: valor encontrado en el plano o informe (con unidades)
- normative_value: valor exigido por el DOTD RDM, citando la ruta exacta del JSON,
  por ejemplo: "DOTD RDM shoulder_width.Interstate_Urban.right_shoulder_minimum = 8 ft"
- complies: true si el valor encontrado cumple, false si no cumple
- observation: comentario adicional si aplica (especialmente en casos de \
  pending_confirmation o cuando el margen de incumplimiento sea pequeño)
- severity: nivel de severidad de la observación — usa "critico", "moderado" o \
  "informativo"; omite el campo (null) si el parámetro cumple

REGLA ESPECIAL — ZONA SIN ESCURRIMIENTO (severidad automática "critico"):
Si encuentras que la pendiente longitudinal = 0% Y la pendiente transversal = 0% \
de forma simultánea en el mismo tramo, genera una observación adicional con:
  parameter: "Drenaje superficial — pendientes simultáneas en 0%"
  complies: false
  severity: "critico"
  observation: "FALLA DE DISEÑO: Pendiente longitudinal 0% y pendiente transversal \
0% simultáneas crean una zona sin escurrimiento. El agua no tiene dirección de \
drenaje en ningún plano. Requiere rediseño inmediato o solución de drenaje forzado \
documentada."
Esta condición aplica independientemente de la longitud del tramo.

Si solo UNA de las dos pendientes es 0% pero la otra no, genera una observación con \
severity: "moderado" indicando que se debe verificar la capacidad de drenaje en la \
dirección de pendiente nula.

REGLA ESPECIAL — PERALTE INVERTIDO (severidad automática "critico"):
Busca en el texto la dirección de cada curva horizontal (RT = Right Turn / giro a la \
derecha; LT = Left Turn / giro a la izquierda) y la dirección del peralte mostrada \
en la sección transversal o en la tabla de superelevación.

Regla de consistencia:
  - Curva RT → la calzada debe inclinarse hacia la DERECHA (interior de la curva).
    Si el plano muestra inclinación hacia la IZQUIERDA con curva RT → PERALTE INVERTIDO.
  - Curva LT → la calzada debe inclinarse hacia la IZQUIERDA.
    Si el plano muestra inclinación hacia la DERECHA con curva LT → PERALTE INVERTIDO.

Caso real de referencia (I-10 Calcasieu River Bridge):
  Ramp R-17, Δ = 180°15'25.5" RT, peralte = 7.20% mostrado hacia la izquierda \
en la sección transversal → PERALTE INVERTIDO confirmado.

Si detectas peralte invertido en cualquier tramo, genera una observación con:
  parameter: "Peralte invertido — [identificador del tramo, p.ej. Ramp R-17]"
  found_value: "[valor del peralte] hacia [dirección mostrada en plano] / curva [RT o LT]"
  normative_value: "DOTD RDM superelevation: curva RT → inclinación hacia la derecha; \
curva LT → inclinación hacia la izquierda. Ref: AASHTO Green Book §3.3."
  complies: false
  severity: "critico"
  observation: "PERALTE INVERTIDO: Superelevación en dirección contraria a la curva. \
La fuerza centrífuga no está contrarrestada — riesgo de accidente. Corrección inmediata \
requerida."

Genera una observación separada por cada tramo con peralte invertido encontrado.

Usa la herramienta report_observations para entregar los resultados."""

USER_TEMPLATE = """Analiza el siguiente texto de plano o informe vial y extrae \
las observaciones de cumplimiento contra la normativa DOTD Louisiana Road Design Manual:

{text}"""
