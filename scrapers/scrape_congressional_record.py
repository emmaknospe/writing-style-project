#!/usr/bin/env python3
"""Scrape Abigail Spanberger's floor speeches and submitted statements from
the Congressional Record (2019-2024 House career) via govinfo.

Uses the govinfo search API to discover every daily-edition CREC granule
mentioning "Ms. SPANBERGER", downloads each granule's plain text from the
public www.govinfo.gov content URLs (no API key needed for those), and
extracts only the paragraphs she actually speaks — from a paragraph opening
with "Ms. SPANBERGER." up to the next speaker turn. Granules where she is
merely mentioned (sponsor lists, roll calls) yield no speaking block and are
skipped.

Discovery goes through the keyless search backend of the govinfo website
(www.govinfo.gov/wssearch/search) rather than api.govinfo.gov, whose
DEMO_KEY tier is too rate-limited to page through the results.
"""
import html as htmllib
import json
import re
import sys
import time
import urllib.error
import urllib.request

from corpus_lib import (
    HEADERS, RAW_PUBLIC_DIR, fetch, slugify, parse_loose_date,
    make_meta, write_frontmatter,
)

SEARCH_URL = "https://www.govinfo.gov/wssearch/search"
QUERY = 'collection:(CREC) content:"Ms. SPANBERGER"'

# Paragraph that begins a different speaker's turn (or the chair speaking),
# ending a Spanberger block.
OTHER_SPEAKER = re.compile(
    r"^(The (Acting )?SPEAKER|The PRESIDING OFFICER|The CHAIR|The Clerk"
    r"|(Mr|Ms|Mrs|Miss)\. [A-Z][A-Za-z'’-]+( of [A-Z][a-zA-Z ]+?)?\.\s)"
)
SPANBERGER_TURN = re.compile(r"^Ms\. SPANBERGER( of Virginia)?\.\s")


def search_granules():
    """Yield deduped granule dicts from the paged website search backend.
    `offset` is a 0-based page number at the given pageSize."""
    seen = set()
    page = 0
    while True:
        payload = json.dumps({
            "facets": {}, "filterOrder": [], "facetToExpand": "",
            "offset": page, "query": QUERY, "pageSize": "100",
            "sortBy": "2", "browseByDate": False, "historical": False,
        }).encode()
        req = urllib.request.Request(
            SEARCH_URL, data=payload,
            headers={**HEADERS, "Content-Type": "application/json"},
        )
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.load(resp)
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 and e.code < 500:
                    raise
                wait = 30 * (attempt + 1)
                print(f"  search returned {e.code}; retrying in {wait}s",
                      file=sys.stderr)
                time.sleep(wait)
        else:
            raise RuntimeError("govinfo wssearch kept returning 429")
        rows = data.get("resultSet") or []
        for r in rows:
            fm = r.get("fieldMap", {})
            gid = fm.get("granuleid")
            if not gid or gid in seen:
                continue
            seen.add(gid)
            yield {
                "granuleId": gid,
                "packageId": fm.get("packageid"),
                "title": fm.get("title", gid),
                "dateIssued": parse_loose_date(r.get("line2", "")),
            }
        # a short (or empty) page is the last one; requesting past the end
        # returns HTTP 500, not an empty result set
        if len(rows) < 100:
            return
        page += 1
        time.sleep(1.0)


def fetch_retry(url, attempts=4):
    for attempt in range(attempts):
        try:
            return fetch(url)
        except urllib.error.HTTPError as e:
            if (e.code != 429 and e.code < 500) or attempt == attempts - 1:
                raise
            wait = 15 * (attempt + 1)
            print(f"  {e.code} on {url}; retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)


def granule_text(package_id, granule_id):
    url = f"https://www.govinfo.gov/content/pkg/{package_id}/html/{granule_id}.htm"
    rawhtml = fetch_retry(url)
    pre_m = re.search(r"<pre>(.*)</pre>", rawhtml, re.S)
    frag = pre_m.group(1) if pre_m else rawhtml
    # Not corpus_lib.strip_tags: that collapses leading whitespace, and the
    # two-space indent is what marks a paragraph start in CREC layout.
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", frag))
    # Page markers (and the blank lines around them) are typography, not
    # content; collapse them so they don't split a paragraph mid-sentence.
    text = re.sub(r"\n\s*\n\[\[Page [^\]]+\]\]\n\s*\n", "\n", text)
    text = re.sub(r"\[\[Page [^\]]+\]\]", "", text)
    text = text.replace("<bullet>", "")
    return url, text


def paragraphs(text):
    """Rebuild paragraphs from the hard-wrapped CREC layout, where a new
    paragraph starts on a line indented exactly two spaces."""
    paras = []
    cur = []
    for line in text.split("\n"):
        if re.match(r"^ {2}\S", line) and not line.startswith("   "):
            if cur:
                paras.append(" ".join(cur))
            cur = [line.strip()]
        elif line.strip():
            cur.append(line.strip())
        else:
            if cur:
                paras.append(" ".join(cur))
                cur = []
    if cur:
        paras.append(" ".join(cur))
    return paras


def extract_speech(text):
    """Return Spanberger's spoken/submitted paragraphs, or "" if none."""
    out = []
    capturing = False
    for para in paragraphs(text):
        if SPANBERGER_TURN.match(para):
            capturing = True
            out.append(para)
        elif capturing:
            # an all-caps paragraph is a section heading: her speech is over
            if (OTHER_SPEAKER.match(para) or re.match(r"^_{4,}", para)
                    or para.isupper()):
                capturing = False
            else:
                out.append(para)
    return "\n\n".join(out)


def display_title(raw):
    title = raw.strip()
    if title.isupper():
        title = title.title().replace("'S", "'s")
    return title


def main():
    print(f"Searching govinfo for: {QUERY}", file=sys.stderr)
    granules = list(search_granules())
    print(f"Discovered {len(granules)} granules.\n", file=sys.stderr)

    seen_bodies = {}  # normalized body -> (url, filename)
    used_fnames = set()
    written = skipped = 0
    for g in granules:
        package_id, granule_id = g["packageId"], g["granuleId"]
        try:
            url, text = granule_text(package_id, granule_id)
        except Exception as e:
            print(f"ERROR fetching {granule_id}: {e}", file=sys.stderr)
            continue

        body = extract_speech(text)
        if not body:
            skipped += 1
            time.sleep(0.3)
            continue

        date_iso = g.get("dateIssued")
        if not date_iso:
            print(f"SKIP (no date parsed): {granule_id}", file=sys.stderr)
            continue
        title = display_title(g.get("title", granule_id))
        # PgE granules are Extensions of Remarks: statements she submitted
        # in writing rather than delivered on the floor.
        is_extension = "-PgE" in granule_id
        notes = (
            "Extension of Remarks (written statement submitted to the record)."
            if is_extension else "Floor remarks."
        )

        norm_key = re.sub(r"\s+", " ", body).strip()
        duplicate_of = None
        if norm_key in seen_bodies:
            dup_url, dup_fname = seen_bodies[norm_key]
            duplicate_of = dup_url
            notes += f" Duplicate posting; identical body already saved as {dup_fname}."
            print(f"DUPLICATE: {granule_id}", file=sys.stderr)

        fname = f"{date_iso}-crec-{slugify(title)[:70]}.md"
        if fname in used_fnames:
            page_ref = granule_id.rsplit("-", 1)[-1].lower()
            fname = f"{date_iso}-crec-{slugify(title)[:60]}-{page_ref}.md"
        used_fnames.add(fname)
        if not duplicate_of:
            seen_bodies[norm_key] = (url, fname)

        meta = make_meta(
            title=title,
            date=date_iso,
            location="U.S. House of Representatives",
            source_name="Congressional Record (govinfo.gov)",
            source_url=url,
            body=body,
            notes=notes,
            duplicate_of=duplicate_of,
        )
        write_frontmatter(RAW_PUBLIC_DIR / fname, meta, body)
        written += 1
        if written % 25 == 0:
            print(f"...{written} written so far", file=sys.stderr)
        time.sleep(0.3)

    print(
        f"\nDone. Wrote {written} files; skipped {skipped} granules with no "
        "Spanberger speaking block.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
