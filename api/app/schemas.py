"""Request and response models for the talking-points endpoint.

`TalkingPointsBrief` doubles as the agent's `output_type`, so its field
descriptions are part of the prompt the model sees -- they carry the sourcing
rules (verbatim quotes, no invented URLs) that the system prompt states in
prose. Keep the two in sync when editing either.
"""

from pydantic import BaseModel, Field


class CorpusCitation(BaseModel):
    """A passage from Spanberger's own remarks backing a talking point."""

    quote: str = Field(
        description=(
            "A verbatim excerpt from a passage returned by search_corpus. Copy "
            "the wording exactly -- do not paraphrase, tidy, or combine "
            "passages."
        )
    )
    title: str = Field(description="The title shown in brackets on the search_corpus hit.")
    date: str = Field(description="The date shown on the search_corpus hit (YYYY-MM-DD).")
    source_url: str = Field(
        description=(
            "The exact Source URL printed under the passage in the "
            "search_corpus output. Never construct or guess a URL."
        )
    )


class WebCitation(BaseModel):
    """A current fact from web search that the corpus cannot supply."""

    claim: str = Field(description="What this source establishes, in one sentence.")
    title: str = Field(description="The title of the page, as returned by web search.")
    url: str = Field(
        description=(
            "The exact URL returned by web search. Never construct or guess a "
            "URL; citations whose URL did not appear in a search result are "
            "discarded before the brief is returned."
        )
    )


class TalkingPoint(BaseModel):
    """One message to land at the event, with its supporting evidence."""

    headline: str = Field(description="A short label for the point, a few words.")
    talking_point: str = Field(
        description=(
            "The substance of the point, written as something the Governor "
            "could say aloud at this event."
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


class TalkingPointsBrief(BaseModel):
    """A prep brief for a single upcoming event."""

    event_summary: str = Field(
        description="What the event is, restated from the request in one or two sentences."
    )
    framing: str = Field(
        description="How to frame the appearance overall -- the through-line connecting the points."
    )
    points: list[TalkingPoint] = Field(description="The talking points, most important first.")
    likely_questions: list[str] = Field(
        default_factory=list,
        description="Questions press or attendees are likely to ask at this event.",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description=(
            "Topics this event calls for where the corpus held no relevant "
            "prior remarks. Say so here instead of stretching a loosely "
            "related passage to cover it."
        ),
    )


class BriefRequest(BaseModel):
    """A free-text description of the event to prepare for."""

    prompt: str
