"""The classification taxonomy: the closed vocabularies tag.py asks Claude to
choose from, the prompt, and the tool schema that forces structured output.

Changing anything here should come with a TAXONOMY_VERSION bump -- the version
is part of tag.py's cache key, so bumping it invalidates every cached label and
forces a full re-tag on the next run.
"""

TAXONOMY_VERSION = "v2"

# One per document. Decides which intermediate/<visibility>/<category>/ folder
# the document is written to, so these strings are also directory names.
CATEGORIES = {
    "speech": (
        "A transcript or full text of remarks she delivered aloud to an "
        "audience: inaugural and inauguration addresses, addresses to the "
        "General Assembly, keynotes, commencement speeches, victory and "
        "concession speeches, rally remarks. Usually released under a "
        "'FULL REMARKS' or 'AS PREPARED FOR DELIVERY' heading."
    ),
    "floor-statement": (
        "Remarks she delivered on the floor of the U.S. House, as recorded in "
        "the Congressional Record. Spoken, procedural context, often addressed "
        "to 'Mr. Speaker' or 'Madam Speaker'."
    ),
    "extension-of-remarks": (
        "A written statement she submitted to the Congressional Record rather "
        "than delivering aloud -- typically honoring a constituent, business, "
        "or organization. Congressional Record source, but not spoken."
    ),
    "campaign-ad": (
        "The script or transcript of a television, radio, or digital campaign "
        "advertisement. Short (usually well under 300 words), often with "
        "voiceover or on-screen-text markers, and written to be performed."
    ),
    "press-release": (
        "An official announcement written in the third person about her or her "
        "administration: appointments, bill signings, grant and investment "
        "announcements, event advisories, endorsements. Typically leads with a "
        "dateline and refers to her as 'Governor Spanberger' throughout."
    ),
    "statement": (
        "A short reactive comment attributed to her responding to a specific "
        "event or decision -- usually titled 'Statement on ...' or 'Statement "
        "Regarding ...'. Distinguished from press-release by being primarily a "
        "quoted reaction rather than an announcement of an action."
    ),
    "op-ed": (
        "A bylined opinion piece written by her for publication in a newspaper "
        "or outlet. First person, argumentative, written to be read."
    ),
    "interview": (
        "A transcript or substantial excerpt of her answering questions -- "
        "television hits, podcast appearances, press gaggles, debates. "
        "Contains an interviewer's questions or clearly marked Q&A structure."
    ),
    "proclamation": (
        "A formal executive instrument: proclamations, executive orders and "
        "directives, flag orders, official declarations of a day or month. "
        "Ceremonial or legal register, often with 'WHEREAS' / 'NOW, THEREFORE' "
        "structure."
    ),
    "media-coverage": (
        "Third-party journalism about her, reposted or excerpted -- a "
        "newspaper or TV story written by a reporter, not by her or her staff. "
        "The words are the outlet's. Use this even when she is quoted at "
        "length, as long as the surrounding article is the outlet's reporting."
    ),
    "internal-document": (
        "A staff-facing working document rather than anything published: fact "
        "sheets, briefing memos, background references, run-of-show and "
        "prep material. Written to be used inside an office, not read by the "
        "public -- headed and dated, often terse, addressed to colleagues or "
        "to the principal. Never her own voice, even when it quotes her. "
        "Everything in this corpus so labeled is synthetic and says so in its "
        "title and notes."
    ),
}

# Where the file goes when the model fails twice or returns something invalid.
# Not a real category; tag.py logs these and ingest ignores the folder.
UNCLASSIFIED = "unclassified"

# How much of the document is actually her own prose. This is the field that
# matters most for a writing-style corpus: a press release that paraphrases her
# in the third person is not a sample of her voice, even though it is "about"
# her and contains a quote or two.
VOICES = {
    "first-person": (
        "Substantially all of the body is her own words -- a speech "
        "transcript, an op-ed under her byline, an ad she narrates, her floor "
        "remarks."
    ),
    "mixed": (
        "A third-person body (staff- or reporter-written) that contains "
        "directly quoted passages from her. Typical of press releases."
    ),
    "third-party": (
        "None of the body is her own words: reporting, announcements, or "
        "advisories that describe her without quoting her at any length."
    ),
}

# Topic tags. Closed vocabulary so the values stay aggregatable; the model
# picks 0-4 and is told to prefer fewer.
TAG_VOCABULARY = [
    "affordability",
    "agriculture",
    "appointments",
    "economy",
    "education",
    "energy",
    "environment",
    "federal-workforce",
    "healthcare",
    "housing",
    "immigration",
    "infrastructure",
    "legislation",
    "national-politics",
    "public-safety",
    "reproductive-rights",
    "rural-virginia",
    "small-business",
    "taxes",
    "transportation",
    "veterans",
    "voting-rights",
    "workforce-development",
]


def _bullets(mapping):
    return "\n".join(f"- {k}: {v}" for k, v in mapping.items())


SYSTEM_PROMPT = f"""\
You classify documents in a corpus of Abigail Spanberger's public \
communications (U.S. Representative for VA-07, then candidate for and now \
Governor of Virginia). The corpus is used to study and retrieve her writing \
and speaking style, so the distinction between her own words and words written \
about her is the most important judgment you make.

Assign exactly one category:
{_bullets(CATEGORIES)}

Assign exactly one voice:
{_bullets(VOICES)}

Assign 0-4 topic tags, only from this list, preferring fewer:
{', '.join(TAG_VOCABULARY)}

Also produce a display_title: the document's title cleaned up for a reader. \
Strip trailing date suffixes ("Serve - May 10, 2018" -> "Serve"), strip \
newsroom prefixes ("FULL REMARKS:", "ICYMI:", "NEW:", "WATCH:", "TODAY:", \
"What Virginians Are Seeing:"), and strip a leading "Governor Spanberger \
Delivers " or "Governor Abigail Spanberger Delivers " where what remains still \
names the document. Otherwise leave the title alone. Never invent a title that \
is not supported by the original, and never return an empty display_title.

Report confidence between 0 and 1: how sure you are of the category, given \
that some documents genuinely sit between two. Below 0.5 means you are \
guessing.

Judge from the body text, not the title alone -- newsroom titles are often \
misleading about the form of what follows."""


# Sent with strict: true and a forced tool_choice, so the API guarantees the
# enums and the required keys. Structured outputs reject numeric bounds
# (minimum/maximum) and array constraints (maxItems), so the "0-4 tags" and
# "confidence in [0,1]" rules live in the prompt and in validate() instead of
# the schema. additionalProperties: false is required by strict mode.
CLASSIFY_TOOL = {
    "name": "classify_document",
    "description": "Record the classification of one corpus document.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "One short sentence justifying the category and voice. "
                    "Answer this first -- it is not stored, but it makes the "
                    "rest of the fields follow from a stated rationale."
                ),
            },
            "category": {
                "type": "string",
                "enum": sorted(CATEGORIES),
                "description": "The single best-fitting document form.",
            },
            "voice": {
                "type": "string",
                "enum": sorted(VOICES),
                "description": "How much of the body is her own words.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string", "enum": TAG_VOCABULARY},
                "description": "Between 0 and 4 topic tags, preferring fewer.",
            },
            "display_title": {
                "type": "string",
                "description": "The title cleaned up for a reader.",
            },
            "confidence": {
                "type": "number",
                "description": (
                    "Confidence in the category assignment, between 0 and 1."
                ),
            },
        },
        "required": [
            "reason", "category", "voice", "tags", "display_title", "confidence",
        ],
        "additionalProperties": False,
    },
}


def validate(result):
    """Check a tool-call payload against the closed vocabularies. Returns a
    list of human-readable problems; empty means valid."""
    problems = []
    if result.get("category") not in CATEGORIES:
        problems.append(f"category {result.get('category')!r} is not in the taxonomy")
    if result.get("voice") not in VOICES:
        problems.append(f"voice {result.get('voice')!r} is not in the taxonomy")

    tags = result.get("tags")
    if not isinstance(tags, list):
        problems.append("tags must be a list")
    else:
        unknown = [t for t in tags if t not in TAG_VOCABULARY]
        if unknown:
            problems.append(f"tags not in the vocabulary: {unknown}")
        if len(tags) > 4:
            problems.append(f"{len(tags)} tags given, at most 4 allowed")

    if not str(result.get("display_title", "")).strip():
        problems.append("display_title is empty")

    confidence = result.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        problems.append(f"confidence {confidence!r} is not a number in [0, 1]")

    return problems
