"""Tests for verbatim-quote checking.

The two `REAL FAILURE` cases are quotes an actual model run produced against
this corpus, each attached to a genuine source URL. They are the reason this
check exists -- URL validation alone accepted both.

Run from `api/`:  python -m pytest tests/
"""

from app.quotes import is_verbatim, normalize

# Retrieved chunk text, as `search_corpus` returns it. Note both begin
# mid-sentence: ingest chunks on a 220-word window, not on sentences.
CHUNK_TALENT = (
    "competing against 49 other states for the best talent in America — and "
    "the businesses that follow that talent. If we do not act, we will lose "
    "that competition. On my watch as Governor, I do not intend to lose. I "
    "intend to dominate. But we have some work to do"
)
CHUNK_CHILDCARE = (
    "ic competitiveness. When a family can’t afford childcare, often times a "
    "parent drops out of the workforce altogether. That’s not just a"
)


class TestAccepts:
    def test_exact_substring(self):
        assert is_verbatim("we will lose that competition.", [CHUNK_TALENT])

    def test_whole_chunk(self):
        assert is_verbatim(CHUNK_TALENT, [CHUNK_TALENT])

    def test_em_dash_rendered_as_hyphen(self):
        assert is_verbatim(
            "the best talent in America - and the businesses", [CHUNK_TALENT]
        )

    def test_curly_apostrophe_rendered_straight(self):
        assert is_verbatim("When a family can't afford childcare", [CHUNK_CHILDCARE])

    def test_collapsed_whitespace(self):
        assert is_verbatim("I  do   not\nintend to lose.", [CHUNK_TALENT])

    def test_ellipsis_elides_material(self):
        assert is_verbatim(
            "competing against 49 other states ... I intend to dominate.", [CHUNK_TALENT]
        )

    def test_unicode_ellipsis_elides_material(self):
        assert is_verbatim(
            "competing against 49 other states … I intend to dominate.", [CHUNK_TALENT]
        )

    def test_finds_quote_in_second_chunk(self):
        assert is_verbatim("drops out of the workforce", [CHUNK_TALENT, CHUNK_CHILDCARE])


class TestRejects:
    def test_real_failure_words_prepended_to_repair_fragment(self):
        """Chunk starts mid-sentence; model added "We are " to make it read whole."""
        assert not is_verbatim(
            "We are competing against 49 other states for the best talent in America",
            [CHUNK_TALENT],
        )

    def test_real_failure_invented_clause_spliced_in(self):
        """Model inserted "and the numbers bear it out, oftentimes a mom"."""
        assert not is_verbatim(
            "When a family cannot afford childcare, oftentimes a parent — and the "
            "numbers bear it out, oftentimes a mom — drops out of the workforce "
            "altogether,",
            [CHUNK_CHILDCARE],
        )

    def test_quote_from_a_different_source(self):
        assert not is_verbatim("we will lose that competition.", [CHUNK_CHILDCARE])

    def test_ellipsis_segments_out_of_order(self):
        assert not is_verbatim(
            "I intend to dominate. ... competing against 49 other states", [CHUNK_TALENT]
        )

    def test_empty_quote(self):
        assert not is_verbatim("   ", [CHUNK_TALENT])

    def test_ellipsis_only(self):
        assert not is_verbatim("...", [CHUNK_TALENT])

    def test_no_chunks_retrieved(self):
        assert not is_verbatim("we will lose that competition.", [])

    def test_paraphrase(self):
        assert not is_verbatim(
            "We are competing with other states for the best workers", [CHUNK_TALENT]
        )


class TestNormalize:
    def test_folds_typography_and_collapses_whitespace(self):
        assert normalize("  “A’s”  —  B C  ") == "\"A's\" - B C"

    def test_leaves_words_alone(self):
        assert normalize("cannot") == "cannot"
