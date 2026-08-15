#!/usr/bin/env python3
"""Scrape all Spanberger entries from the Archives of Women's Political
Communication (Iowa State Catt Center) directory page. Auto-discovers every
linked item (no hardcoded slug list) and auto-parses date from the
directory listing text. Role is inferred automatically from date via
corpus_lib.

The official governor.virginia.gov inaugural address transcript is treated
as canonical (see scrape_governor_va.py), so this scraper skips AWPC's copy
of that same speech to avoid a near-duplicate.
"""
import re
import sys
import time

from corpus_lib import (
    SPEECHES_DIR, fetch, strip_tags, slugify, parse_loose_date, make_meta,
    write_frontmatter,
)

DIRECTORY_URL = "https://awpc.cattcenter.iastate.edu/directory/abigail-spanberger"
BASE = "https://awpc.cattcenter.iastate.edu/communication/"

SKIP_SLUGS = {
    # canonical version scraped from governor.virginia.gov instead
    "gov-abigail-spanbergers-inaugural-address-january-17-2026",
}


def discover_items():
    dir_html = fetch(DIRECTORY_URL)
    items = re.findall(r'<a href="/communication/([a-z0-9-]+)">([^<]+)</a>', dir_html)
    # dedupe while preserving order
    seen = set()
    out = []
    for slug, link_text in items:
        if slug in seen:
            continue
        seen.add(slug)
        out.append((slug, htmldecode(link_text)))
    return out


def htmldecode(s):
    import html as htmllib
    return htmllib.unescape(s).strip()


def extract(rawhtml, url):
    title_m = re.search(r'<h1 class="hero--news-article__headline">(.*?)</h1>', rawhtml, re.S)
    title = strip_tags(title_m.group(1)) if title_m else ""

    loc_m = re.search(r"<strong>Location:</strong>\s*([^<]+)", rawhtml)
    location = strip_tags(loc_m.group(1)) if loc_m else ""

    body_section_m = re.search(
        r'paragraph-widget--text-content">\s*<div class="text-content">(.*?)</div>\s*</div>',
        rawhtml, re.S,
    )
    if not body_section_m:
        return None
    body_html = re.sub(r"<aside.*?</aside>", "", body_section_m.group(1), flags=re.S)
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.S)
    clean_paras = [strip_tags(p) for p in paragraphs]
    clean_paras = [p for p in clean_paras if p]
    body_text = "\n\n".join(clean_paras)

    return {"title": title, "location": location, "body": body_text, "url": url}


def main():
    print(f"Fetching directory: {DIRECTORY_URL}", file=sys.stderr)
    items = discover_items()
    print(f"Discovered {len(items)} linked items.\n", file=sys.stderr)

    written = 0
    for slug, link_text in items:
        if slug in SKIP_SLUGS:
            print(f"SKIP (canonical version used instead): {slug}", file=sys.stderr)
            continue

        url = BASE + slug
        print(f"Fetching {url} ...", file=sys.stderr)
        try:
            rawhtml = fetch(url)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            continue

        data = extract(rawhtml, url)
        if not data or not data["body"]:
            print("  WARNING: no body extracted, skipping", file=sys.stderr)
            continue

        date_iso = parse_loose_date(link_text) or parse_loose_date(data["title"])
        if not date_iso:
            print(f"  WARNING: could not parse date from '{link_text}', skipping", file=sys.stderr)
            continue

        meta = make_meta(
            title=data["title"],
            date=date_iso,
            location=data["location"],
            source_name="Archives of Women's Political Communication (Iowa State University, Catt Center)",
            source_url=data["url"],
            body=data["body"],
        )
        fname = f"{date_iso}-awpc-{slugify(data['title'])[:70]}.md"
        write_frontmatter(SPEECHES_DIR / fname, meta, data["body"])
        written += 1
        print(f"  Saved {fname} (role={meta['role']})", file=sys.stderr)
        time.sleep(0.3)

    print(f"\nDone. Wrote {written} files.", file=sys.stderr)


if __name__ == "__main__":
    main()
