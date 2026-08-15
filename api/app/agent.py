from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from app.config import settings

SYSTEM_PROMPT = (
    "You are a helpful assistant for the writing-style project. "
    "Answer clearly and concisely."
)


def build_agent() -> Agent:
    model = AnthropicModel(
        settings.anthropic_model,
        provider=AnthropicProvider(api_key=settings.anthropic_api_key),
    )
    return Agent(model, system_prompt=SYSTEM_PROMPT)


chat_agent = build_agent()
