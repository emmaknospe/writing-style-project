"""Verbatim-quote checking for corpus citations.

Kept free of config and network imports so it can be tested on its own --
`app.agent` builds a live Anthropic client at import time, which a unit test
should not need.

The job: decide whether a quote the model attributed to a passage actually
appears in the text retrieval served. Strict about words, forgiving about
typography, because the observed failure is a model splicing an invented
sub-clause into an otherwise real sentence -- not a stray curly apostrophe.
"""

# Typography the model routinely normalises while copying: curly quotes,
# dashes, non-breaking spaces. Folding these keeps the check strict about
# *words* without failing on punctuation the model rendered differently.
_TYPOGRAPHY = str.maketrans(
    {
        "‘": "'",  # left single quote
        "’": "'",  # right single quote / apostrophe
        "‛": "'",
        "“": '"',  # left double quote
        "”": '"',  # right double quote
        "–": "-",  # en dash
        "—": "-",  # em dash
        "−": "-",  # minus
        " ": " ",  # non-breaking space
    }
)


def normalize(text: str) -> str:
    """Fold typography and collapse whitespace, leaving words untouched."""
    return " ".join(text.translate(_TYPOGRAPHY).split())


def is_verbatim(quote: str, chunks: list[str]) -> bool:
    """Whether `quote` appears word-for-word in one of `chunks`.

    An ellipsis is honoured as elision: each segment must appear in a single
    chunk, in order. Everything else must match exactly (after typography
    folding) -- including quotes that begin or end mid-sentence, which happens
    routinely because ingest chunks on a word window rather than on sentences.
    Tempting as it is to allow the model to tidy such a fragment into a whole
    sentence, that is exactly how words she never said get added.
    """
    segments = [
        normalize(segment)
        for segment in quote.replace("…", "...").split("...")
        if normalize(segment)
    ]
    if not segments:
        return False

    for chunk in chunks:
        haystack = normalize(chunk)
        cursor = 0
        for segment in segments:
            found = haystack.find(segment, cursor)
            if found == -1:
                break
            cursor = found + len(segment)
        else:
            return True
    return False
