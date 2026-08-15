"""LLM output contracts for the brief agents.

Deliberately separate from `app/schemas.py`: those are wire DTOs, these are
*prompt surface*. Every `Field` description here is read by the model, so they
carry the sourcing rules the system prompts state in prose. Keep the two in
sync when editing either.

Citations name a corpus chunk by its **Qdrant point id** rather than by title
and URL. The server resolves the id, checks the quote against that chunk's
text, and fills the bibliographic fields from the stored payload -- so the
model cannot invent citation metadata even in principle.
"""

from pydantic import BaseModel, Field


class CorpusCitation(BaseModel):
    """A passage from Spanberger's own remarks, pinned to an exact chunk."""

    point_id: str = Field(
        description=(
            "The `id:` printed on the search_corpus passage this quote comes "
            "from. Copy it exactly; never invent one. A citation whose id was "
            "not returned by a search is discarded."
        )
    )
    quote: str = Field(
        description=(
            "A word-for-word excerpt from that passage. Passages are cut on a "
            "word window and may begin or end mid-sentence -- quote as-is and "
            "do not add words to complete a sentence. Use an ellipsis (...) to "
            "skip material; that is the only edit allowed."
        )
    )


class WebCitation(BaseModel):
    """A current fact from web search that the corpus cannot supply."""

    claim: str = Field(description="What this source establishes, in one sentence.")
    title: str = Field(description="The page title, as returned by web search.")
    url: str = Field(
        description=(
            "The exact URL returned by web search. Never construct or guess "
            "one; citations whose URL did not appear in a result are discarded."
        )
    )


# --- phase 1: the outline put to the user for approval ----------------------


class ProposedPoint(BaseModel):
    """One angle the brief could take. No prose yet -- that waits for approval."""

    headline: str = Field(description="A short label for the angle, a few words.")
    rationale: str = Field(
        description=(
            "Why this angle belongs at this event, and what evidence backs it. "
            "One or two sentences, written for the user deciding whether to "
            "keep it."
        )
    )
    corpus_point_ids: list[str] = Field(
        default_factory=list,
        description=(
            "`id:` values of search_corpus passages that would support this "
            "point. Empty is meaningful -- it says the corpus offers nothing "
            "and the point would rest on web context alone."
        ),
    )
    web_urls: list[str] = Field(
        default_factory=list,
        description="URLs from web search that would support this point.",
    )


class BriefOutline(BaseModel):
    """What the agent proposes to cover, before writing anything."""

    event_summary: str = Field(
        description="What the event is, restated from the request in one or two sentences."
    )
    framing: str = Field(
        description="The through-line connecting the proposed points."
    )
    proposed_points: list[ProposedPoint] = Field(
        description="The angles to cover, most important first."
    )
    likely_questions: list[str] = Field(
        default_factory=list,
        description="Questions press or attendees are likely to ask at this event.",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description=(
            "Topics this event calls for where the corpus held no relevant "
            "prior remarks. Say so here rather than stretching a loosely "
            "related passage to cover it."
        ),
    )
    questions_for_user: list[str] = Field(
        default_factory=list,
        description=(
            "Decisions you need from the user before drafting -- an ambiguous "
            "audience, a policy they may not want raised. Leave empty if the "
            "request is clear."
        ),
    )


# --- phase 2: the drafted brief ---------------------------------------------


class DraftedPoint(BaseModel):
    """A talking point written against one approved outline entry."""

    headline: str = Field(
        description="The heading of the outline point this drafts. Keep the user's wording."
    )
    talking_point: str = Field(
        description=(
            "The substance, written as something the Governor could say aloud "
            "at this event -- not a description of her position."
        )
    )
    corpus_support: list[CorpusCitation] = Field(
        default_factory=list,
        description=(
            "Prior remarks backing this point. Leave empty rather than citing "
            "a passage that is only loosely related."
        ),
    )
    web_context: list[WebCitation] = Field(
        default_factory=list,
        description="Current facts from web search relevant to this point.",
    )


class DraftedPoints(BaseModel):
    """The drafting pass over an approved outline.

    `points` must correspond to the approved outline, in order: the user has
    already decided what the brief covers, so this pass writes those points
    rather than re-choosing them.
    """

    points: list[DraftedPoint] = Field(
        description="One entry per approved outline point, in the same order."
    )
    framing: str | None = Field(
        default=None,
        description=(
            "A revised through-line, only if the approved outline changed "
            "enough to need one. Omit to keep the existing framing."
        ),
    )
    likely_questions: list[str] = Field(
        default_factory=list,
        description="Questions to expect, revised in light of the approved outline.",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Topics the approved outline calls for that the corpus cannot support.",
    )
