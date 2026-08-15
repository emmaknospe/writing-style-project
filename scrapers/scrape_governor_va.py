#!/usr/bin/env python3
"""Scrape ALL press releases (not just full-text speeches) issued by
Governor Abigail Spanberger's office on governor.virginia.gov, from her
inauguration (Jan 2026) through the current month. Auto-discovers monthly
archive pages and every release linked from them; writes one .md file per
release with standardized YAML frontmatter (see corpus_lib.py).
"""
import datetime
import re
import sys
import time

from corpus_lib import (
    RAW_PUBLIC_DIR, fetch, strip_tags, slugify, make_meta, write_frontmatter,
)

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

START_YEAR, START_MONTH = 2026, 1  # inauguration month


def month_range():
    today = datetime.date.today()
    y, m = START_YEAR, START_MONTH
    while (y, m) <= (today.year, today.month):
        yield y, MONTH_NAMES[m - 1]
        m += 1
        if m > 12:
            m = 1
            y += 1


def discover_release_urls():
    urls = []
    for year, month_name in month_range():
        listing_url = f"https://www.governor.virginia.gov/newsroom/news-releases/{year}/{month_name}-releases/"
        try:
            listing_html = fetch(listing_url)
        except Exception as e:
            print(f"  (no listing for {month_name} {year}: {e})", file=sys.stderr)
            continue
        found = sorted(set(re.findall(
            rf'href="(/newsroom/news-releases/{year}/{month_name}-releases/name-\d+-en\.html)"',
            listing_html,
        )))
        print(f"{month_name} {year}: {len(found)} releases", file=sys.stderr)
        urls.extend(f"https://www.governor.virginia.gov{path}" for path in found)
    return urls


def extract(rawhtml, url):
    title_m = re.search(r'<meta property="og:title" content="([^"]*)"', rawhtml)
    if not title_m:
        return None
    title = strip_tags(title_m.group(1))

    date_m = re.search(r"For Immediate Release:\s*</strong>\s*([^<]+)", rawhtml)
    date_raw = strip_tags(date_m.group(1)) if date_m else ""
    date_iso = None
    if date_raw:
        m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", date_raw)
        if m:
            try:
                dt = datetime.datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y")
                date_iso = dt.date().isoformat()
            except ValueError:
                pass

    press_m = re.search(r'<div class="pressrelease">(.*?)</div></div></div></div></div></section>', rawhtml, re.S)
    if not press_m:
        return None
    press_html = press_m.group(1)

    body_m = re.search(r'<div class="mt-3">(.*)$', press_html, re.S)
    if not body_m:
        return None
    body_html = body_m.group(1)

    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.S)
    clean_paras = [strip_tags(p) for p in paragraphs]
    clean_paras = [p for p in clean_paras if p and p != "# # #"]
    body_text = "\n\n".join(clean_paras)

    location_m = re.search(r"<strong>([A-Z][A-Za-z .]+,\s*V[Aa]\.?)</strong>", body_html)
    location = location_m.group(1).strip() if location_m else ""

    return {"title": title, "date": date_iso, "location": location, "body": body_text, "url": url}


def main():
    urls = discover_release_urls()
    print(f"\nDiscovered {len(urls)} total press release URLs.\n", file=sys.stderr)

    seen_bodies = {}  # normalized body -> (url, filename)
    written = 0
    for url in urls:
        try:
            rawhtml = fetch(url)
        except Exception as e:
            print(f"ERROR fetching {url}: {e}", file=sys.stderr)
            continue

        data = extract(rawhtml, url)
        if not data or not data["body"] or not data["date"]:
            print(f"SKIP (no body/date): {url}", file=sys.stderr)
            continue

        norm_key = re.sub(r"\s+", " ", data["body"]).strip()

        fname = f"{data['date']}-govva-{slugify(data['title'])[:70]}.md"
        fpath = RAW_PUBLIC_DIR / fname

        duplicate_of = None
        notes = ""
        if norm_key in seen_bodies:
            dup_url, dup_fname = seen_bodies[norm_key]
            duplicate_of = dup_url
            notes = f"Duplicate posting; identical body already saved as {dup_fname}."
            print(f"DUPLICATE: {url} == {dup_url}", file=sys.stderr)
        else:
            seen_bodies[norm_key] = (url, fname)

        meta = make_meta(
            title=data["title"],
            date=data["date"],
            location=data["location"],
            source_name="governor.virginia.gov",
            source_url=data["url"],
            body=data["body"],
            notes=notes,
            duplicate_of=duplicate_of,
        )
        write_frontmatter(fpath, meta, data["body"])
        written += 1
        if written % 20 == 0:
            print(f"...{written} written so far", file=sys.stderr)
        time.sleep(0.3)

    print(f"\nDone. Wrote {written} press release files.", file=sys.stderr)


if __name__ == "__main__":
    main()
