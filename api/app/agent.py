import asyncio

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from app.config import settings
from app.embeddings import embed_query
from app.vector_store import search as vector_search

SYSTEM_PROMPT = (
    "You are a helpful assistant for the writing-style project, which answers "
    "questions about Virginia Governor Abigail Spanberger's speeches and "
    "campaign ads using a corpus of her public remarks.\n\n"
    "Use the search_corpus tool whenever a question concerns something "
    "Spanberger said, her positions, a specific speech or ad, or needs a "
    "quote or citation from her remarks -- search first rather than relying "
    "on prior knowledge. For general questions unrelated to the corpus, "
    "answer directly without using the tool.\n\n"
    "When you answer using retrieved passages, cite the source (title, "
    "speaker, and date) so the user can verify it. If the tool returns no "
    "relevant passages, say so plainly rather than guessing."
)


def build_agent() -> Agent:
    model = AnthropicModel(
        settings.anthropic_model,
        provider=AnthropicProvider(api_key=settings.anthropic_api_key),
    )
    agent = Agent(model, system_prompt=SYSTEM_PROMPT)

    @agent.tool_plain
    async def search_corpus(query: str) -> str:
        """Search Abigail Spanberger's speech and ad corpus for passages
        relevant to a query. Returns the top matching passages with their
        title, speaker, date, speech type, and source URL, or a message
        saying nothing relevant was found.

        Args:
            query: A natural-language description of what to search for
                (e.g. a topic, position, or specific speech/ad).
        """
        vector = await asyncio.to_thread(embed_query, query)
        hits = await asyncio.to_thread(vector_search, vector, settings.rag_top_k)
        if not hits:
            return "No relevant passages found in the corpus."
        return "\n\n---\n\n".join(
            f"[{hit.get('title')} -- {hit.get('speaker')}, {hit.get('date')}, "
            f"{hit.get('speech_type')}] (relevance={hit['score']:.3f})\n"
            f"{hit.get('text')}\n"
            f"Source: {hit.get('source_url')}"
            for hit in hits
        )

    return agent


chat_agent = build_agent()
