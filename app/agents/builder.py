"""Builder: writes the MVP - a digital guide/template pack - rendered by code to Markdown + static HTML."""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Optional

from app.agents import base
from app.models import PRD, GuidePack


def run(run_id: str, prd: PRD, failures: Optional[list[str]] = None, previous: Optional[GuidePack] = None) -> GuidePack:
    ctx: dict = {"prd": prd}
    instr = ("Write the complete guide/template pack. Use exactly the required section headings from the PRD. "
             "Each section needs real, practical content (at least 80 words). Add 1-3 fill-in templates.")
    if failures:
        ctx["test_failures"] = failures
        ctx["previous_version"] = previous
        instr = "Fix every test failure listed. " + instr
    return base.run(run_id, "builder", "builder", "build_guide_pack" if not failures else "revise_guide_pack", GuidePack,
                    ctx, instructions=instr)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "section"


def to_markdown(pack: GuidePack) -> str:
    parts = [f"# {pack.title}", "", pack.intro, "", "## Contents", ""]
    parts += [f"- [{s.heading}](#{slug(s.heading)})" for s in pack.sections]
    for s in pack.sections:
        parts += ["", f"## {s.heading}", "", s.body_markdown.strip()]
    for t in pack.templates:
        parts += ["", f"## Template: {t.name}", "", t.body_markdown.strip()]
    return "\n".join(parts) + "\n"


def _md_inline(text: str) -> str:
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', t)
    return t


def md_to_html(md: str, title: str) -> str:
    out, in_list = [], False
    for line in md.splitlines():
        if line.startswith("- ") or line.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_md_inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        m = re.match(r"^(#{1,4}) (.*)$", line)
        if m:
            lvl, text = len(m.group(1)), m.group(2)
            out.append(f'<h{lvl} id="{slug(text)}">{_md_inline(text)}</h{lvl}>')
        elif line.strip():
            out.append(f"<p>{_md_inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    body = "\n".join(out)
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"></head>\n<body>\n{body}\n</body></html>\n')


def write(pack: GuidePack, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = to_markdown(pack)
    md_path, html_path = out_dir / "guide.md", out_dir / "guide.html"
    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(md_to_html(md, pack.title), encoding="utf-8")
    return md_path, html_path
