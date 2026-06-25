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

    async def validate(self, text: str) -> list[AASHTOObservation]:
        message = await self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "report_observations"},
            messages=[
                {"role": "user", "content": USER_TEMPLATE.format(text=text)},
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
