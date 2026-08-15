#!/usr/bin/env python3
"""Scrape every post from Abigail Spanberger's 2025 gubernatorial campaign
site (abigailspanberger.com, still live) via its open WordPress REST API.

Covers Nov 2023 through the present. Each post is tagged in `notes` with its
WordPress category so downstream ingest can filter:
  - press-release: campaign press releases (campaign's own prose)
  - op-eds:        pieces authored by Spanberger herself
  - news:          reposted third-party media coverage (NOT her words)
"""
import json
import re
import sys
import time
import urllib.request

from corpus_lib import (
    SPEECHES_DIR, HEADERS, strip_tags, slugify, make_meta, write_frontmatter,
)

API_BASE = "https://abigailspanberger.com/wp-json/wp/v2"


def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def category_map():
    cats = get_json(f"{API_BASE}/categories?per_page=100")
    return {c["id"]: c["slug"] for c in cats}


def all_posts():
    page = 1
    while True:
        url = f"{API_BASE}/posts?per_page=100&page={page}&orderby=date&order=asc"
        try:
            batch = get_json(url)
        except urllib.error.HTTPError as e:
            if e.code == 400:  # past the last page
                return
            raise
        if not batch:
            return
        yield from batch
        page += 1
        time.sleep(0.5)


def body_from_html(content_html):
    content_html = re.sub(r"<(script|style|iframe).*?</\1>", "", content_html, flags=re.S)
    paras = re.findall(r"<p[^>]*>(.*?)</p>", content_html, re.S)
    clean = [strip_tags(p) for p in paras]
    clean = [p for p in clean if p and p != "###"]
    if clean:
        return "\n\n".join(clean)
    return strip_tags(content_html)


def main():
    cat_slugs = category_map()
    print(f"Categories: {cat_slugs}", file=sys.stderr)

    written = 0
    used_fnames = set()
    seen_bodies = {}  # normalized body -> (url, filename)
    for post in all_posts():
        date_iso = post["date"][:10]
        title = strip_tags(post["title"]["rendered"])
        body = body_from_html(post["content"]["rendered"])
        if not body:
            print(f"SKIP (empty body): {post['link']}", file=sys.stderr)
            continue

        cats = [cat_slugs.get(cid, str(cid)) for cid in post.get("categories", [])]
        notes = f"Campaign site post; categories: {', '.join(cats) or 'none'}."
        if "news" in cats and "op-eds" not in cats and "press-release" not in cats:
            notes += " Reposted third-party media coverage — not Spanberger's own words."

        norm_key = re.sub(r"\s+", " ", body).strip()
        duplicate_of = None
        if norm_key in seen_bodies:
            dup_url, dup_fname = seen_bodies[norm_key]
            duplicate_of = dup_url
            notes += f" Duplicate posting; identical body already saved as {dup_fname}."
            print(f"DUPLICATE: {post['link']} == {dup_url}", file=sys.stderr)

        meta = make_meta(
            title=title,
            date=date_iso,
            location="",
            source_name="abigailspanberger.com (2025 campaign site)",
            source_url=post["link"],
            body=body,
            notes=notes,
            duplicate_of=duplicate_of,
        )
        fname = f"{date_iso}-camp-{slugify(title)[:70]}.md"
        if fname in used_fnames:  # disambiguate with WP's unique post id
            fname = f"{date_iso}-camp-{slugify(title)[:60]}-{post['id']}.md"
        used_fnames.add(fname)
        if not duplicate_of:
            seen_bodies[norm_key] = (post["link"], fname)
        write_frontmatter(SPEECHES_DIR / fname, meta, body)
        written += 1
        if written % 50 == 0:
            print(f"...{written} written so far", file=sys.stderr)

    print(f"\nDone. Wrote {written} campaign post files.", file=sys.stderr)


if __name__ == "__main__":
    main()
