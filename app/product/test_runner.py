"""Product test runner (plain Python, no LLM). Exit code 0 = all checks pass.

Usage: python -m app.product.test_runner <product_dir> <spec.json> [report.json]
Checks: structure (headings, sections, words), forbidden phrases, link check, HTML validation, spelling.
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Validator(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.ids: set[str] = set()
        self.hrefs: list[str] = []
        self.has_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
        a = dict(attrs)
        if "id" in a:
            if a["id"] in self.ids:
                self.errors.append(f"duplicate id '{a['id']}'")
            self.ids.add(a["id"])
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])
        if tag == "title":
            self.has_title = True
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()


def _sections(md: str) -> dict[str, str]:
    out: dict[str, str] = {}
    current = None
    for line in md.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            current = m.group(1).strip()
            out[current] = ""
        elif current:
            out[current] += line + "\n"
    return out


def spelling_error_rate(text: str) -> tuple[float, list[str]]:
    try:
        from spellchecker import SpellChecker
    except ImportError:
        return 0.0, []
    words = [w for w in re.findall(r"\b[a-z][a-z']{3,}\b", text)]  # lowercase words only: skips names/acronyms
    if not words:
        return 0.0, []
    sc = SpellChecker()
    unknown = sc.unknown(words)
    bad = [w for w in words if w in unknown]
    return len(bad) / len(words), sorted(set(bad))[:20]


def run(product_dir: Path, spec: dict[str, Any]) -> dict[str, Any]:
    md = (product_dir / "guide.md").read_text(encoding="utf-8")
    html = (product_dir / "guide.html").read_text(encoding="utf-8")
    failures: list[str] = []
    sections = _sections(md)
    lower_heads = {h.lower(): h for h in sections}
    for req in spec["required_headings"]:
        if req.lower() not in lower_heads:
            failures.append(f"structure: missing required heading '## {req}'")
    content_sections = {h: b for h, b in sections.items() if h.lower() != "contents" and not h.lower().startswith("template:")}
    if len(content_sections) < spec["min_sections"]:
        failures.append(f"structure: {len(content_sections)} sections < {spec['min_sections']}")
    for h, body in content_sections.items():
        n = len(re.findall(r"\w+", body))
        if n < spec["min_words_per_section"]:
            failures.append(f"structure: section '{h}' has {n} words < {spec['min_words_per_section']}")
    for p in spec.get("forbidden_phrases", []):
        if p.lower() in md.lower():
            failures.append(f"content: forbidden phrase '{p}'")
    v = _Validator()
    v.feed(html)
    if not html.lstrip().lower().startswith("<!doctype html>"):
        failures.append("html: missing <!doctype html>")
    if not v.has_title:
        failures.append("html: missing <title>")
    failures += [f"html: {e}" for e in v.errors[:10]]
    if v.stack:
        failures.append(f"html: unclosed tags {v.stack}")
    for href in v.hrefs:
        if href.startswith("#"):
            if href[1:] not in v.ids:
                failures.append(f"links: broken anchor {href}")
        elif not re.match(r"^(https?://[\w.-]+\.[a-z]{2,}|mailto:)", href):
            failures.append(f"links: invalid link {href}")
    rate, words = spelling_error_rate(md)
    if rate > spec.get("max_spelling_error_rate", 0.08):
        failures.append(f"spelling: error rate {rate:.1%} > {spec.get('max_spelling_error_rate', 0.08):.0%} ({', '.join(words[:8])})")
    return {"passed": not failures, "failures": failures, "spelling_error_rate": round(rate, 4),
            "sections": len(content_sections), "links_checked": len(v.hrefs)}


def main(argv: list[str]) -> int:
    product_dir, spec_path = Path(argv[1]), Path(argv[2])
    report = run(product_dir, json.loads(spec_path.read_text(encoding="utf-8")))
    if len(argv) > 3:
        Path(argv[3]).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
