#!/usr/bin/env python3
"""
Verify Markdown source anchors used in tutorials point to existing files/lines.

Supported reference forms:
- GitHub-style links with line anchors: [text](../../api/path/to/file.py#L220) or ranges #L220-L297
- Inline backticks with repo-relative file references: `api/path/to/file.py:220` or `api/file.py:220-297`

Exit code:
- 0: all references valid
- 1: one or more invalid references found

Usage:
  python dev/tools/verify_md_anchors.py                 # scan tutorials/backend/*.md
  python dev/tools/verify_md_anchors.py path/glob.md    # custom glob(s)

Tip: run from the repo root.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


MD_DEFAULT_GLOB = "tutorials/backend/*.md"


@dataclass(frozen=True)
class Reference:
    md_file: Path
    md_line: int
    target_file: Path
    line_start: int | None
    line_end: int | None
    raw: str


def find_markdown_links(md_path: Path, content: str) -> Iterator[Reference]:
    # Matches [text](path#L123) or [text](path#L10-L20)
    link_re = re.compile(r"\[[^\]]*\]\((?P<href>[^)\s]+)\)")
    line_anchor_re = re.compile(r"#L(?P<start>\d+)(?:-(?:L)?(?P<end>\d+))?$")

    for i, line in enumerate(content.splitlines(), start=1):
        for m in link_re.finditer(line):
            href = m.group("href")
            # Skip http(s) links or pure fragment
            if "://" in href or href.startswith("#"):
                continue

            # Split path and optional #fragment
            if "#" in href:
                path_str, frag = href.split("#", 1)
                anchor_m = line_anchor_re.match("#" + frag)
                if not anchor_m:
                    # Non-line anchor; ignore
                    continue
                start = int(anchor_m.group("start"))
                end = int(anchor_m.group("end")) if anchor_m.group("end") else None
            else:
                path_str = href
                start = end = None

            # Resolve path relative to markdown file
            path = (md_path.parent / Path(path_str)).resolve()
            yield Reference(md_file=md_path, md_line=i, target_file=path, line_start=start, line_end=end, raw=line.strip())


def find_inline_code_refs(md_path: Path, content: str, repo_root: Path) -> Iterator[Reference]:
    # Matches `api/path/to/file.py:220` or range with hyphen/en-dash
    code_re = re.compile(r"`(?P<ref>[^`]+)`")
    # Normalize en dash to hyphen later
    for i, line in enumerate(content.splitlines(), start=1):
        for m in code_re.finditer(line):
            ref = m.group("ref").strip()
            # Only consider refs that look like file:line
            if ":" not in ref:
                continue
            path_part, line_part = ref.rsplit(":", 1)
            # Skip Windows drive letter edge case (C:\...)
            if len(path_part) == 1 and path_part.isalpha():
                continue
            line_part = line_part.replace("–", "-")  # en dash → hyphen
            start: int | None
            end: int | None
            if "-" in line_part:
                try:
                    s, e = line_part.split("-", 1)
                    start = int(s)
                    end = int(e)
                except ValueError:
                    continue
            else:
                try:
                    start = int(line_part)
                    end = None
                except ValueError:
                    continue

            # Resolve repo-relative paths (no leading slash assumed)
            target = (repo_root / path_part).resolve()
            yield Reference(md_file=md_path, md_line=i, target_file=target, line_start=start, line_end=end, raw=line.strip())


def iter_references(md_files: Iterable[Path]) -> Iterator[Reference]:
    repo_root = Path(__file__).resolve().parents[2]
    for md in md_files:
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        yield from find_markdown_links(md, text)
        yield from find_inline_code_refs(md, text, repo_root)


def validate_reference(ref: Reference) -> tuple[bool, str | None]:
    # File existence
    if not ref.target_file.exists() or not ref.target_file.is_file():
        return False, f"missing file: {ref.target_file}"

    try:
        # NOTE: read once and count lines
        total = sum(1 for _ in ref.target_file.open("r", encoding="utf-8", errors="ignore"))
    except Exception as e:
        return False, f"cannot read file: {e}"

    # Line checks
    if ref.line_start is not None:
        if ref.line_start <= 0 or ref.line_start > total:
            return False, f"line {ref.line_start} out of range (1..{total})"
    if ref.line_end is not None:
        if ref.line_end <= 0 or ref.line_end > total:
            return False, f"line {ref.line_end} out of range (1..{total})"
        if ref.line_start is not None and ref.line_end < ref.line_start:
            return False, f"invalid range {ref.line_start}-{ref.line_end}"
    return True, None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate Markdown source anchors in tutorials")
    parser.add_argument("patterns", nargs="*", default=[MD_DEFAULT_GLOB], help="Glob patterns of markdown files")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show valid references as well")
    args = parser.parse_args(argv)

    md_files: list[Path] = []
    for pat in args.patterns:
        md_files.extend(Path().glob(pat))

    if not md_files:
        print("No markdown files matched.")
        return 1

    errors: list[str] = []
    count_ok = 0
    count_all = 0

    for ref in iter_references(md_files):
        count_all += 1
        ok, err = validate_reference(ref)
        if ok:
            count_ok += 1
            if args.verbose:
                print(f"OK {ref.md_file}:{ref.md_line} -> {ref.target_file}:{ref.line_start or ''}{('-'+str(ref.line_end)) if ref.line_end else ''}")
        else:
            errors.append(
                f"ERROR {ref.md_file}:{ref.md_line}: {err}\n    ↳ {ref.raw}\n    ↳ target: {ref.target_file}"
            )

    if errors:
        print("\n".join(errors))
        print(f"\nInvalid references: {len(errors)} / {count_all}. Valid: {count_ok}.")
        return 1

    print(f"All references valid. Checked: {count_all}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

