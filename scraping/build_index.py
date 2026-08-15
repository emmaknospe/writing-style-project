#!/usr/bin/env python3
"""Regenerate speeches/INDEX.md by reading the YAML frontmatter (JSON-subset
scalars, written by corpus_lib.write_frontmatter) out of every .md file in
speeches/. No PyYAML dependency -- frontmatter values are JSON-compatible by
construction, so each `key: value` line is parsed with json.loads.
"""
import json
from collections import Counter

from corpus_lib import SPEECHES_DIR


def parse_frontmatter(text):
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    block = text[4:end]
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
    return meta


def main():
    records = []
    for fpath in SPEECHES_DIR.glob("*.md"):
        if fpath.name == "INDEX.md":
            continue
        meta = parse_frontmatter(fpath.read_text())
        if meta is None:
            print(f"WARNING: no frontmatter in {fpath.name}")
            continue
        records.append((fpath.name, meta))

    records.sort(key=lambda r: (r[1].get("date", ""), r[0]))

    role_counts = Counter(m.get("role", "unknown") for _, m in records)

    lines = ["# Abigail Spanberger — Speech & Communication Corpus Index", ""]
    lines.append(
        f"{len(records)} items. Schema: frontmatter on every file has "
        "`title, speaker, date, role, location, source_name, "
        "source_url, retrieved_date, word_count` and optional "
        "`notes`/`duplicate_of`."
    )
    lines.append("")
    lines.append("## By role")
    lines.append("")
    for r, c in role_counts.most_common():
        lines.append(f"- {r}: {c}")
    lines.append("")
    lines.append("## Full index")
    lines.append("")
    lines.append("| Date | Title | Role | Source | File |")
    lines.append("|---|---|---|---|---|")
    for fname, meta in records:
        title = str(meta.get("title", "")).replace("|", "\\|")
        lines.append(
            f"| {meta.get('date','')} | {title} | {meta.get('role','')} | "
            f"{meta.get('source_name','')} | "
            f"[{fname}]({fname}) |"
        )

    (SPEECHES_DIR / "INDEX.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote INDEX.md with {len(records)} entries.")


if __name__ == "__main__":
    main()
