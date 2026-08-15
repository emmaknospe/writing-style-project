"""The brief agents.

Two agents, not one, because the approval gate has to be structural. The
outline agent's output type has no field capable of holding a talking point, so
it *cannot* skip ahead and draft -- the gate holds even if the prompt is
ignored. The draft agent then runs against the outline as the user left it,
replaying the outline run's message history so the research isn't repeated.

Two grounding sources, deliberately split:

- `search_corpus` (RAG over `data/`) supplies what Spanberger has *already
  said*. The corpus is a fixed snapshot, so it can never speak to an upcoming
  event's specifics.
- Anthropic's server-side web search supplies what is *currently true*. It runs
  on Anthropic's infrastructure, so there is no tool function here to
  implement; pydantic-ai maps `WebSearch` onto the `web_search_20260209`
  server tool.

Citations name a corpus chunk by Qdrant point id. The caller resolves the id
and fills the bibliographic fields from the stored payload, so the model never
supplies citation metadata -- see `verify_corpus_citations` below.
"""

import asyncio
import logging

from pydantic_ai import Agent, NativeOutput
from pydantic_ai.capabilities import WebSearch
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider

from app.agent_outputs import BriefOutline, CorpusCitation, DraftedPoints
from app.config import settings
from app.embeddings import embed_query
from app.quotes import is_verbatim
from app.vector_store import get_by_ids, search as vector_search

logger = logging.getLogger(__name__)

# Shared by both agents: how to research, and the sourcing rules. The phase
# prompts below say what to *produce*; this says how to gather.
_RESEARCH_RULES = (
    "You have two sources, and they answer different questions.\n\n"
    "search_corpus searches a curated corpus of Abigail Spanberger's own past "
    "speeches and campaign ads. It tells you what she has already said and how "
    "she has framed things before. Call it several times -- once per theme the "
    "event plausibly touches -- rather than once with a broad query. A "
    "ribbon-cutting at a factory, for example, is worth separate searches for "
    "jobs, manufacturing, the region, and the economy. The corpus is a fixed "
    "snapshot and knows nothing about the event itself.\n\n"
    "Web search tells you what is currently true: the venue, the host "
    "organisation, recent news about the company or region, anything that has "
    "happened since the corpus was assembled. Use it for the event's specifics "
    "and current facts -- never as a substitute for the corpus when the "
    "question is what she has said.\n\n"
    "Sourcing rules, which matter more than coverage:\n"
    "- Every corpus passage is printed with an `id:`. Cite a passage by that "
    "id, copied exactly. Never invent an id, and never cite a passage you did "
    "not retrieve in this conversation.\n"
    "- Quote the corpus word for word. Passages are cut on a word window, so "
    "one may begin or end mid-sentence -- quote it as it stands and do not add "
    "words to make it a complete sentence. To skip material inside a quote use "
    "an ellipsis (...); that is the only edit allowed.\n"
    "- Do not paraphrase, modernise wording, or add clauses. Putting words she "
    "did not say into a quotation attributed to her is the worst thing you can "
    "do here. Quotes are checked against the retrieved text and any that do "
    "not match word for word are dropped.\n"
    "- If the corpus has nothing genuinely relevant to a theme the event calls "
    "for, record that as a gap. Do not stretch a loosely related passage to "
    "cover it. A brief that admits a gap is more useful than one that papers "
    "over it."
)

OUTLINE_PROMPT = (
    "You prepare talking-point briefs for Virginia Governor Abigail "
    "Spanberger. The user describes an upcoming event.\n\n"
    "Your job in this phase is research and a proposed outline -- NOT the "
    "talking points themselves. Research the event thoroughly, then propose "
    "the angles the brief should take, each with a short rationale and the "
    "evidence you found for it. The user will edit this outline before "
    "anything is drafted, so write rationales for a person deciding what to "
    "keep, and raise anything you genuinely need decided.\n\n" + _RESEARCH_RULES
)

DRAFT_PROMPT = (
    "You prepare talking-point briefs for Virginia Governor Abigail "
    "Spanberger. An outline has been researched and then reviewed and edited "
    "by the user.\n\n"
    "Draft the talking points for that outline. The user has already decided "
    "what the brief covers: write one point per outline entry, in the given "
    "order, keeping their headings. Do not add, drop, merge, or reorder "
    "points. If an entry was edited or added by hand it may need fresh "
    "searching -- do that before writing it.\n\n"
    "Write each point as something the Governor could say aloud at this event, "
    "not as a description of her position.\n\n" + _RESEARCH_RULES
)


def _format_hits(hits: list[dict]) -> str:
    """Render corpus hits for the model, leading with the id it must cite."""
    if not hits:
        return "No relevant passages found in the corpus."
    return "\n\n---\n\n".join(
        f"id: {hit.get('id')}\n"
        f"[{hit.get('title')} -- {hit.get('speaker')}, {hit.get('date')}, "
        f"{hit.get('speech_type')}] (relevance={hit['score']:.3f})\n"
        f"{hit.get('text')}"
        for hit in hits
    )


async def search_corpus(query: str) -> str:
    """Search Abigail Spanberger's speech and ad corpus for passages relevant
    to a query. Returns the top matching passages, each with the `id:` to cite
    it by, its title, speaker, date and speech type, and the passage text.

    Call this once per theme the event touches rather than once with a broad
    query -- narrow queries retrieve better.

    Args:
        query: A natural-language description of what to search for
            (e.g. a topic, position, or specific speech/ad).
    """
    vector = await asyncio.to_thread(embed_query, query)
    hits = await asyncio.to_thread(vector_search, vector, settings.brief_top_k)
    return _format_hits(hits)


def _build(system_prompt: str, output_type):
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

    return Agent(
        model,
        # NativeOutput, not the default tool-output mode. These schemas nest
        # three levels deep, and asking Claude to produce that as a *tool
        # argument* fails: it intermittently emits the list field as a string of
        # pseudo-XML (`<parameter name="headline">...`) instead of a list, which
        # fails validation and burns the retry. Anthropic's native structured
        # outputs constrain decoding server-side, so the JSON is schema-valid by
        # construction.
        output_type=NativeOutput(output_type),
        system_prompt=system_prompt,
        tools=[search_corpus],
        capabilities=capabilities,
        # pydantic-ai defaults to 4096, which truncates a brief mid-JSON; the
        # response then fails validation with fields simply missing, which reads
        # like a model error rather than a length one.
        model_settings=AnthropicModelSettings(max_tokens=settings.max_output_tokens),
    )


outline_agent = _build(OUTLINE_PROMPT, BriefOutline)
draft_agent = _build(DRAFT_PROMPT, DraftedPoints)


def verify_corpus_citations(
    citations: list[CorpusCitation],
) -> tuple[list[dict], int, int]:
    """Resolve citations against Qdrant, dropping any the corpus doesn't support.

    Returns `(verified, unknown_id_count, not_verbatim_count)`, where each
    verified entry is ready to become a `section_sources` row: the quote as the
    model wrote it, plus title/speaker/date/url taken from the **stored
    payload**, never from the model. That is the point of citing by id -- the
    model supplies only a pointer and a quote, so it cannot misattribute a real
    passage to the wrong speech or date.

    Two independent checks, because they catch different failures. An unknown
    id is an invented source. A non-verbatim quote is worse and commoner: a
    real source with words the speaker never said -- observed in testing as an
    invented sub-clause spliced into an otherwise real sentence, which no
    amount of id checking would catch.

    Dropping rather than retrying: a bad citation usually sits alongside sound
    ones, so this keeps the rest of the brief. A point that loses its citation
    still stands -- it just no longer claims she said it.
    """
    if not citations:
        return [], 0, 0

    chunks = {c["id"]: c for c in get_by_ids([c.point_id for c in citations])}

    verified: list[dict] = []
    unknown_id = not_verbatim = 0
    for citation in citations:
        chunk = chunks.get(citation.point_id)
        if chunk is None:
            unknown_id += 1
            continue
        if not is_verbatim(citation.quote, [chunk.get("text") or ""]):
            not_verbatim += 1
            logger.warning(
                "dropped non-verbatim quote attributed to %r: %.120s",
                chunk.get("title"),
                citation.quote,
            )
            continue
        verified.append(
            {
                "qdrant_point_id": citation.point_id,
                "quoted_text": citation.quote,
                "title": chunk.get("title"),
                "speaker": chunk.get("speaker"),
                "date": chunk.get("date"),
                "speech_type": chunk.get("speech_type"),
                "source_url": chunk.get("source_url"),
                "source_file": chunk.get("source_file"),
                "chunk_index": chunk.get("chunk_index"),
            }
        )

    if unknown_id or not_verbatim:
        logger.warning(
            "dropped %d corpus citation(s): %d unknown id, %d not verbatim",
            unknown_id + not_verbatim,
            unknown_id,
            not_verbatim,
        )
    return verified, unknown_id, not_verbatim
