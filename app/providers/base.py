from abc import ABC, abstractmethod
from app.schemas.aashto import AASHTOObservation


class BaseLLMProvider(ABC):
    @abstractmethod
    async def validate(self, text: str, params: dict | None = None) -> list[AASHTOObservation]:
        ...
