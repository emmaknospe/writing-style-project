#!/usr/bin/env python3
"""Shared helpers for the corpus: reading and writing Markdown files with
standardized YAML frontmatter, plus the scraping utilities that produce them.

This module is the single home for frontmatter I/O -- the scrapers, the
tagging stage, and the ingest stage all round-trip through
`parse_frontmatter` / `write_frontmatter` here.

Metadata schema (frontmatter keys):

  Source fields, written by the scrapers into raw/:
    title, speaker, date (YYYY-MM-DD), role, location, source_name,
    source_url, retrieved_date, word_count, [notes], [duplicate_of]

  Classification fields, added by tagging/tag.py into intermediate/:
    display_title, category, voice, tags, classifier, classifier_confidence

Every *source* field is read directly off the source page or mechanically
derived (role from date, word_count from body, duplicate_of from
exact-body-match detection) -- scrapers never guess. Classification is a
separate, explicit stage: an LLM assigns those fields, and `classifier`
records which model and taxonomy version did it so any label can be traced
and invalidated. Neither stage uses keyword heuristics.
"""
import datetime
import html as htmllib
import json
import re
import urllib.request
from pathlib import Path

# Pipeline roots. Scrapers write raw/public/; tagging/tag.py reads raw/ and
# writes intermediate/<visibility>/<category>/; ingest reads intermediate/.
_REPO_ROOT = Path(__file__).parent.parent
RAW_DIR = _REPO_ROOT / "raw"
RAW_PUBLIC_DIR = RAW_DIR / "public"
INTERMEDIATE_DIR = _REPO_ROOT / "intermediate"
SPEAKER = "Abigail Spanberger"
RETRIEVED_DATE = datetime.date.today().isoformat()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# Date ranges -> role. Ordered; first match wins. Each is (start_date_inclusive, end_date_exclusive_or_None, role).
ROLE_TIMELINE = [
    (datetime.date(2026, 1, 17), None, "Governor of Virginia"),
    (datetime.date(2025, 11, 4), datetime.date(2026, 1, 17), "Governor-elect of Virginia"),
    (datetime.date(2025, 1, 1), datetime.date(2025, 11, 4), "Gubernatorial candidate"),
    (datetime.date(2019, 1, 3), datetime.date(2025, 1, 1), "U.S. Representative (VA-07)"),
    (datetime.date(1900, 1, 1), datetime.date(2019, 1, 3), "Congressional candidate (VA-07)"),
]


def infer_role(date_str):
    """date_str: YYYY-MM-DD. Returns a role string from ROLE_TIMELINE."""
    d = datetime.date.fromisoformat(date_str)
    for start, end, role in ROLE_TIMELINE:
        if d >= start and (end is None or d < end):
            return role
    return "unknown"


def slugify(text):
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def strip_tags(fragment):
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    text = htmllib.unescape(fragment)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text.strip()


MONTHS = (
    "January|Jan\\.?|February|Feb\\.?|March|Mar\\.?|April|Apr\\.?|May|"
    "June|Jun\\.?|July|Jul\\.?|August|Aug\\.?|September|Sept\\.?|Sep\\.?|"
    "October|Oct\\.?|November|Nov\\.?|December|Dec\\.?"
)
MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_loose_date(text):
    """Parse a date like 'Aug. 4, 2025', 'September 28, 2018', 'Nov. 5, 2018'
    out of arbitrary text. Returns YYYY-MM-DD or None."""
    m = re.search(rf"({MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})", text)
    if not m:
        return None
    month_raw, day, year = m.group(1), m.group(2), m.group(3)
    key = re.sub(r"[.\s]", "", month_raw).lower()[:4]
    key = key if key in MONTH_MAP else key[:3]
    month = MONTH_MAP.get(key) or MONTH_MAP.get(month_raw.rstrip(".").lower()[:3])
    if not month:
        return None
    return f"{int(year):04d}-{month:02d}-{int(day):02d}"


def word_count(body):
    return len(body.split())


# Press releases carry a shouted dateline city ("RICHMOND, VA"). Everything
# else in the corpus is already clean ("U.S. House of Representatives",
# "Virginia", ""), so only that one shape is rewritten.
_DATELINE_RE = re.compile(r"^([A-Za-z][A-Za-z .'-]*),\s*Va\.?$", re.IGNORECASE)


def normalize_location(location):
    """'RICHMOND, VA' -> 'Richmond, Virginia'. Anything that isn't a shouted
    Virginia dateline is returned unchanged."""
    text = (location or "").strip()
    m = _DATELINE_RE.match(text)
    if not m:
        return text
    return f"{m.group(1).strip().title()}, Virginia"


def yaml_scalar(value):
    """Render a Python value as a YAML-safe scalar/flow value using JSON
    encoding (a valid subset of YAML) -- avoids needing PyYAML."""
    return json.dumps(value, ensure_ascii=False)


# Written for every document, in this order.
SOURCE_KEYS = [
    "title", "speaker", "date", "role", "location",
    "source_name", "source_url", "retrieved_date", "word_count",
]
# Added by tagging/tag.py. Written only when present, so raw/ files keep the
# source schema and intermediate/ files carry both.
CLASSIFIER_KEYS = [
    "display_title", "category", "voice", "tags",
    "classifier", "classifier_confidence",
]
# Free-text trailers, written last and only when non-empty.
OPTIONAL_KEYS = ["duplicate_of", "notes"]


def parse_frontmatter(text):
    """Parse the JSON-scalar YAML frontmatter written by write_frontmatter.
    Returns (meta_dict, body) or None if the file has no frontmatter block."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    block = text[4:end]
    body = text[end + 5:]
    meta = {}
    for line in block.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        raw_value = raw_value.strip()
        try:
            meta[key] = json.loads(raw_value)
        except json.JSONDecodeError:
            meta[key] = raw_value
    return meta, body.strip()


def read_document(fpath):
    """parse_frontmatter for a Path. Returns (meta, body) or None."""
    return parse_frontmatter(Path(fpath).read_text())


def write_frontmatter(fpath, meta, body):
    lines = ["---"]
    for key in SOURCE_KEYS:
        lines.append(f"{key}: {yaml_scalar(meta[key])}")
    for key in CLASSIFIER_KEYS:
        if meta.get(key) is not None:
            lines.append(f"{key}: {yaml_scalar(meta[key])}")
    for key in OPTIONAL_KEYS:
        if meta.get(key):
            lines.append(f"{key}: {yaml_scalar(meta[key])}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    lines.append("")
    fpath = Path(fpath)
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text("\n".join(lines))


def make_meta(title, date, location, source_name, source_url,
              body, notes="", duplicate_of=None, role=None):
    return {
        "title": title,
        "speaker": SPEAKER,
        "date": date,
        "role": role or infer_role(date),
        "location": location or "",
        "source_name": source_name,
        "source_url": source_url,
        "retrieved_date": RETRIEVED_DATE,
        "word_count": word_count(body),
        "notes": notes,
        "duplicate_of": duplicate_of,
    }
