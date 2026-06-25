from app.providers.anthropic_provider import AnthropicProvider


def get_provider() -> AnthropicProvider:
    return AnthropicProvider()
