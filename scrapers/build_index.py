#!/usr/bin/env python3
"""Regenerate raw/public/INDEX.md by reading the frontmatter out of every .md
file in raw/public/. This indexes the *raw* corpus only -- the classified copies
under intermediate/ are organized by their directory layout instead.
"""
from collections import Counter

from corpus_lib import RAW_PUBLIC_DIR, SOURCE_KEYS, read_document


def main():
    records = []
    for fpath in RAW_PUBLIC_DIR.glob("*.md"):
        if fpath.name == "INDEX.md":
            continue
        parsed = read_document(fpath)
        if parsed is None:
            print(f"WARNING: no frontmatter in {fpath.name}")
            continue
        records.append((fpath.name, parsed[0]))

    records.sort(key=lambda r: (r[1].get("date", ""), r[0]))

    role_counts = Counter(m.get("role", "unknown") for _, m in records)

    lines = ["# Abigail Spanberger — Speech & Communication Corpus Index", ""]
    lines.append(
        f"{len(records)} items. Schema: frontmatter on every file has "
        f"`{', '.join(SOURCE_KEYS)}` and optional `notes`/`duplicate_of`."
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

    (RAW_PUBLIC_DIR / "INDEX.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote INDEX.md with {len(records)} entries.")


if __name__ == "__main__":
    main()
