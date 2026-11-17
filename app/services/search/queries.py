"""Search queries built in code from templates; the planner only supplies keywords (SearchTerms).

Purposes: demand (people describing the problem), competitors (products for this buyer), pricing (a named
competitor's price). YEAR is always the current year; the model never writes a year. Every query passes
`lint` before it is sent; rejected queries are logged with the reason.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from app.models import SearchTerms

DEMAND = ["site:reddit.com {problem}", "site:news.ycombinator.com {problem}", '{problem} "I wish there was"',
          "site:reddit.com {audience} {problem}", '{problem} frustrated OR annoying OR "hate"']
COMPETITORS = ["{product_type} for {audience}", "best {product_type} {audience} {year}"]
SECOND_PASS = ["alternatives to {competitor}"]
PRICING = ["{competitor} pricing"]
PRICING_FALLBACK = "{competitor} price per month"

COPY_WINDOW = 6
PLAIN_BANNED = re.compile(r"\b(forum|forums|discussion|discussions)\b", re.I)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\"'`]", "", s or "")).strip()


def competitor_name(name: str) -> str:
    """A competitor name read from a web page: letters, digits and spaces only, at most 4 words."""
    words = re.sub(r"[^\w\s.&+-]", " ", name or "").split()
    return " ".join(words[:4]) if words and len(words) <= 4 else ""


def _fill(template: str, **kw: str) -> str:
    return re.sub(r"\s+", " ", template.format(**kw)).strip()


def lint(query: str, idea: str = "", year: Optional[int] = None) -> Optional[str]:
    """Return why a query is rejected, or None if it may be sent."""
    year = year or datetime.now().year
    words = query.split()
    if len(words) > 10:
        return f"more than 10 words ({len(words)})"
    for y in re.findall(r"\b(19\d{2}|20\d{2})\b", query):
        if int(y) != year:
            return f"year {y} is not the current year {year}"
    plain = re.sub(r"site:\S+", " ", query)
    if PLAIN_BANNED.search(plain):
        return "uses 'forum'/'discussion' as a plain word (use site: or community engines instead)"
    idea_words = re.findall(r"\w+", (idea or "").lower())
    if len(idea_words) >= COPY_WINDOW:  # keywords naturally overlap the idea; a run of 6 words is a copy
        q = " ".join(re.findall(r"\w+", query.lower()))
        for i in range(len(idea_words) - COPY_WINDOW + 1):
            if " ".join(idea_words[i:i + COPY_WINDOW]) in q:
                return "copies the brief's idea text"
    return None


def build(terms: SearchTerms, purpose: str, *, competitor: str = "", limit: int = 4) -> list[str]:
    year = str(datetime.now().year)
    problem, audience, product = _clean(terms.problem), _clean(terms.audience), _clean(terms.product_type)
    if purpose == "demand":
        out = [_fill(t, problem=problem, audience=audience) for t in DEMAND]
        for syn in [_clean(s) for s in terms.synonyms[:3] if _clean(s)]:
            out += [_fill(t, problem=syn, audience=audience) for t in DEMAND[:2]]
    elif purpose == "competitors":
        out = [_fill(t, product_type=product, audience=audience, year=year) for t in COMPETITORS]
    elif purpose == "alternatives":
        out = [_fill(t, competitor=competitor_name(competitor)) for t in SECOND_PASS] if competitor_name(competitor) else []
    elif purpose == "pricing":
        out = [_fill(t, competitor=competitor_name(competitor)) for t in PRICING] if competitor_name(competitor) else []
    elif purpose == "pricing_fallback":
        out = [_fill(PRICING_FALLBACK, competitor=competitor_name(competitor))] if competitor_name(competitor) else []
    else:
        raise ValueError(purpose)
    seen: list[str] = []
    for q in out:
        if q and q not in seen:
            seen.append(q)
    return seen[:limit]
