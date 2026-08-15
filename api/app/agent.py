import asyncio

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from app.config import settings
from app.embeddings import embed_query
from app.vector_store import search as vector_search

SYSTEM_PROMPT = (
    "You are a helpful assistant for the writing-style project, which answers "
    "questions about Virginia Governor Abigail Spanberger's public "
    "communications using a corpus of them.\n\n"
    "Use the search_corpus tool whenever a question concerns something "
    "Spanberger said, her positions, a specific speech or ad, or needs a "
    "quote or citation from her remarks -- search first rather than relying "
    "on prior knowledge. For general questions unrelated to the corpus, "
    "answer directly without using the tool.\n\n"
    "The corpus spans several forms -- delivered speeches, floor statements, "
    "campaign ads, op-eds, press releases, proclamations -- and each passage "
    "is labeled with its category and its voice. Voice matters: "
    "'first-person' passages are her own words and are the authority on how "
    "she speaks and writes; 'mixed' passages are staff-written text that "
    "quotes her, so only the quoted parts are hers; 'third-party' passages "
    "are not her words at all. When a question is about her voice, style, or "
    "exact wording, rely on first-person passages and say so if the best "
    "available evidence is only a quote inside a press release.\n\n"
    "When you answer using retrieved passages, cite the source (title, "
    "speaker, and date) so the user can verify it. If the tool returns no "
    "relevant passages, say so plainly rather than guessing."
)


def _format_hit(hit: dict) -> str:
    """Render one search hit for the model. display_title is the cleaned-up
    title; fall back to the source-page title on documents that predate it."""
    title = hit.get("display_title") or hit.get("title")
    header = f"{title} -- {hit.get('speaker')}, {hit.get('date')}"
    for key in ("category", "voice"):
        if hit.get(key):
            header += f", {hit[key]}"
    tags = hit.get("tags")
    if tags:
        header += f", tags: {', '.join(tags)}"
    return (
        f"[{header}] (relevance={hit['score']:.3f})\n"
        f"{hit.get('text')}\n"
        f"Source: {hit.get('source_url')}"
    )


def build_agent() -> Agent:
    model = AnthropicModel(
        settings.anthropic_model,
        provider=AnthropicProvider(api_key=settings.anthropic_api_key),
    )
    agent = Agent(model, system_prompt=SYSTEM_PROMPT)

    @agent.tool_plain
    async def search_corpus(query: str) -> str:
        """Search Abigail Spanberger's corpus of public communications for
        passages relevant to a query. Returns the top matching passages with
        their title, speaker, date, category, voice, topic tags, and source
        URL, or a message saying nothing relevant was found.

        Args:
            query: A natural-language description of what to search for
                (e.g. a topic, position, or specific speech/ad).
        """
        vector = await asyncio.to_thread(embed_query, query)
        hits = await asyncio.to_thread(vector_search, vector, settings.rag_top_k)
        if not hits:
            return "No relevant passages found in the corpus."
        return "\n\n---\n\n".join(_format_hit(hit) for hit in hits)

    return agent


chat_agent = build_agent()
