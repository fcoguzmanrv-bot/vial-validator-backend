import anthropic
from app.schemas.compare import VersionChange
from app.core.config import settings

_SYSTEM_PROMPT = """Eres un experto en análisis de planos y documentos de ingeniería vial.
Compara dos versiones de un informe o plano vial e identifica todos los cambios relevantes.

Para cada cambio encontrado indica:
- location: estación kilométrica, elemento o sección donde ocurre el cambio
- change_type: "modificado" si un valor cambió, "agregado" si es nuevo, "eliminado" si desapareció
- description: descripción clara y técnica del cambio
- impact: "crítico" si afecta seguridad o cumplimiento normativo, "moderado" si afecta diseño o costos, "informativo" para cambios menores

Usa la herramienta report_changes para entregar los resultados."""

_USER_TEMPLATE = """Compara las siguientes dos versiones de un documento vial e identifica los cambios.

=== VERSIÓN 1 ===
{text_v1}

=== VERSIÓN 2 ===
{text_v2}"""

_TOOL = {
    "name": "report_changes",
    "description": "Reporta los cambios detectados entre las dos versiones del documento vial.",
    "input_schema": {
        "type": "object",
        "properties": {
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "location":    {"type": "string"},
                        "change_type": {"type": "string", "enum": ["modificado", "agregado", "eliminado"]},
                        "description": {"type": "string"},
                        "impact":      {"type": "string", "enum": ["crítico", "moderado", "informativo"]},
                    },
                    "required": ["location", "change_type", "description", "impact"],
                },
            }
        },
        "required": ["changes"],
    },
}


class CompareProvider:
    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.ANTHROPIC_MODEL

    async def compare(self, text_v1: str, text_v2: str) -> list[VersionChange]:
        message = await self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=_SYSTEM_PROMPT,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "report_changes"},
            messages=[
                {"role": "user", "content": _USER_TEMPLATE.format(text_v1=text_v1, text_v2=text_v2)},
            ],
        )

        tool_block = next(
            (b for b in message.content if b.type == "tool_use"),
            None,
        )
        if tool_block is None:
            raise ValueError("La API no devolvió un bloque tool_use en la respuesta.")

        items = tool_block.input.get("changes", [])
        return [VersionChange(**item) for item in items]
