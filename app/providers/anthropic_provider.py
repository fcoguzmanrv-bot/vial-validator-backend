import anthropic
from app.providers.base import BaseLLMProvider
from app.providers.prompts import SYSTEM_PROMPT, USER_TEMPLATE
from app.schemas.aashto import AASHTOObservation
from app.core.config import settings

# Tool definition that forces Claude to return structured observations
_TOOL = {
    "name": "report_observations",
    "description": "Reporta las observaciones de cumplimiento AASHTO extraídas del informe.",
    "input_schema": {
        "type": "object",
        "properties": {
            "observations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "parameter":       {"type": "string"},
                        "found_value":     {"type": "string"},
                        "normative_value": {"type": "string"},
                        "complies":        {"type": "boolean"},
                        "observation":     {"type": "string"},
                        "severity":        {"type": "string", "enum": ["critico", "moderado", "informativo"]},
                    },
                    "required": ["parameter", "found_value", "normative_value", "complies"],
                },
            }
        },
        "required": ["observations"],
    },
}


class AnthropicProvider(BaseLLMProvider):
    def __init__(self):
        self.client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = settings.ANTHROPIC_MODEL

    def _build_user_message(self, text: str, params: dict | None) -> str:
        p = params or {}
        return USER_TEMPLATE.format(
            functional_class=p.get("functional_class") or "No especificado",
            speed_mainline=p.get("speed_mainline") or "No especificado",
            speed_ramps=p.get("speed_ramps") or "No especificado",
            speed_collector=p.get("speed_collector") or "No especificado",
            speed_loops=p.get("speed_loops") or "No especificado",
            emax=p.get("emax") or "No especificado",
            context=p.get("context") or "No especificado",
            text=text,
        )

    async def validate(self, text: str, params: dict | None = None) -> list[AASHTOObservation]:
        message = await self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "report_observations"},
            messages=[
                {"role": "user", "content": self._build_user_message(text, params)},
            ],
        )

        tool_block = next(
            (b for b in message.content if b.type == "tool_use"),
            None,
        )
        if tool_block is None:
            raise ValueError("La API no devolvió un bloque tool_use en la respuesta.")

        items = tool_block.input.get("observations", [])
        return [AASHTOObservation(**item) for item in items]
