"""The talking-points agent.

Two grounding sources, deliberately split:

- `search_corpus` (RAG over `data/`) supplies what Spanberger has *already
  said*. The corpus is a fixed snapshot, so it can never speak to an upcoming
  event's specifics.
- Anthropic's server-side web search supplies what is *currently true* -- the
  venue, the host organisation, recent local news. It runs on Anthropic's
  infrastructure, so there is no tool function here to implement; pydantic-ai
  maps `WebSearch` onto the `web_search_20260209` server tool.

Both are capped: `search_corpus` by `brief_top_k`, web search by
`web_search_max_uses` (each search is billed on top of tokens).
"""

import asyncio
import logging
from dataclasses import dataclass, field

from pydantic_ai import Agent, NativeOutput, RunContext
from pydantic_ai.capabilities import WebSearch
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider

from app.config import settings
from app.embeddings import embed_query
from app.quotes import is_verbatim
from app.schemas import TalkingPointsBrief
from app.vector_store import search as vector_search

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You prepare talking-point briefs for Virginia Governor Abigail "
    "Spanberger. The user describes an upcoming event; you produce the brief "
    "she would take into it.\n\n"
    "You have two sources, and they answer different questions.\n\n"
    "search_corpus searches a curated corpus of her own past speeches and "
    "campaign ads. It tells you what she has already said and how she has "
    "framed things before. Call it several times -- once per theme the event "
    "plausibly touches -- rather than once with a broad query. A ribbon-"
    "cutting at a factory, for example, is worth separate searches for jobs, "
    "manufacturing, the region, and the economy. The corpus is a fixed "
    "snapshot and knows nothing about the event itself.\n\n"
    "Web search tells you what is currently true: the venue, the host "
    "organisation, recent news about the company or region, anything that has "
    "happened since the corpus was assembled. Use it for the event's "
    "specifics and current facts -- never as a substitute for the corpus when "
    "the question is what she has said.\n\n"
    "Sourcing rules, which matter more than coverage:\n"
    "- Quote the corpus word for word. Copy the wording straight out of the "
    "passage. Do not paraphrase, do not modernise the wording, and do not add "
    "clauses -- putting words she did not say into a quotation attributed to "
    "her is the worst thing you can do here.\n"
    "- Passages are cut on a word window, so a passage may begin or end "
    "mid-sentence. Quote it as it stands; do not add words to make it read as "
    "a complete sentence. To skip material inside a quote, use an ellipsis "
    "(...) -- that is the only edit allowed.\n"
    "- Quotes are checked against the retrieved text before the brief is "
    "returned, and any that do not match word for word are dropped. A point "
    "with no quote is fine; a point with an altered quote is not.\n"
    "- Copy source URLs exactly as the tools print them. Never construct a "
    "URL. Citations whose URL did not come from a tool are dropped before the "
    "brief is returned, so an invented one costs you the citation.\n"
    "- If the corpus has nothing genuinely relevant to a theme the event "
    "calls for, put that in gaps. Do not stretch a loosely related passage to "
    "cover it. A brief that admits a gap is more useful than one that papers "
    "over it.\n\n"
    "Write talking points as things she could say aloud at this event, not as "
    "descriptions of her positions. Order them most important first."
)


@dataclass
class BriefDeps:
    """Per-run record of what retrieval actually returned.

    Keyed by source URL, holding the chunk texts served for it. The output
    validator checks both halves of a citation against this: the URL must be
    one retrieval returned, and the quote must actually appear in the text
    served under it.
    """

    corpus_chunks: dict[str, list[str]] = field(default_factory=dict)


def build_agent() -> Agent[BriefDeps, TalkingPointsBrief]:
    model = AnthropicModel(
        settings.anthropic_model,
        provider=AnthropicProvider(api_key=settings.anthropic_api_key),
    )

    # WEB_SEARCH_MAX_USES=0 means "corpus only" -- useful for iterating on
    # prompts or the UI without paying per search. It has to drop the whole
    # capability rather than pass the 0 through: Anthropic rejects
    # `max_uses: 0` outright with `Input should be greater than 0`.
    capabilities = (
        [WebSearch(max_uses=settings.web_search_max_uses)]
        if settings.web_search_max_uses > 0
        else []
    )

    agent = Agent(
        model,
        deps_type=BriefDeps,
        # NativeOutput, not the default tool-output mode. The brief's schema
        # nests three levels deep (brief -> points -> citations), and asking
        # Claude to produce that as a *tool argument* fails: it intermittently
        # emits `points` as a string of pseudo-XML (`<parameter name="headline">
        # ...`) instead of a list, which fails validation and burns the retry.
        # Anthropic's native structured outputs constrain decoding server-side,
        # so the JSON is schema-valid by construction.
        output_type=NativeOutput(TalkingPointsBrief),
        system_prompt=SYSTEM_PROMPT,
        capabilities=capabilities,
        model_settings=AnthropicModelSettings(max_tokens=settings.max_output_tokens),
    )

    @agent.tool
    async def search_corpus(ctx: RunContext[BriefDeps], query: str) -> str:
        """Search Abigail Spanberger's speech and ad corpus for passages
        relevant to a query. Returns the top matching passages with their
        title, speaker, date, speech type, and source URL, or a message
        saying nothing relevant was found.

        Call this once per theme the event touches rather than once with a
        broad query -- narrow queries retrieve better.

        Args:
            query: A natural-language description of what to search for
                (e.g. a topic, position, or specific speech/ad).
        """
        vector = await asyncio.to_thread(embed_query, query)
        hits = await asyncio.to_thread(vector_search, vector, settings.brief_top_k)
        if not hits:
            return "No relevant passages found in the corpus."

        for hit in hits:
            source_url = hit.get("source_url")
            if source_url:
                ctx.deps.corpus_chunks.setdefault(source_url, []).append(hit.get("text") or "")

        return "\n\n---\n\n".join(
            f"[{hit.get('title')} -- {hit.get('speaker')}, {hit.get('date')}, "
            f"{hit.get('speech_type')}] (relevance={hit['score']:.3f})\n"
            f"{hit.get('text')}\n"
            f"Source: {hit.get('source_url')}"
            for hit in hits
        )

    @agent.output_validator
    def drop_unbacked_corpus_citations(
        ctx: RunContext[BriefDeps], brief: TalkingPointsBrief
    ) -> TalkingPointsBrief:
        """Discard corpus citations that retrieval does not actually support.

        Two independent checks, because they catch different failures. A bad
        URL is an invented source. A bad quote is worse and commoner: a real
        source URL with words the speaker never said -- observed in testing as
        an invented sub-clause spliced into an otherwise real sentence, which
        no amount of URL checking would catch.

        Deliberately a filter rather than a `ModelRetry`: a bad citation
        usually sits alongside sound ones, so dropping it keeps the rest of the
        brief instead of paying for a full regeneration. A point that loses its
        citation still stands on its own -- it just no longer claims she said
        it.
        """
        bad_url = bad_quote = 0
        for point in brief.points:
            kept = []
            for citation in point.corpus_support:
                chunks = ctx.deps.corpus_chunks.get(citation.source_url)
                if chunks is None:
                    bad_url += 1
                elif not is_verbatim(citation.quote, chunks):
                    bad_quote += 1
                    logger.warning(
                        "dropped non-verbatim quote attributed to %r: %.120s",
                        citation.title,
                        citation.quote,
                    )
                else:
                    kept.append(citation)
            point.corpus_support = kept

        if bad_url or bad_quote:
            logger.warning(
                "dropped %d corpus citation(s): %d unknown URL, %d not verbatim",
                bad_url + bad_quote,
                bad_url,
                bad_quote,
            )
        return brief

    return agent


brief_agent = build_agent()
