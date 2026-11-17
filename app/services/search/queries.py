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

# Demand: web search only finds people talking about a problem on pages we may read. Reddit and Hacker News
# come from their APIs (app/services/community); SearXNG ignores site: operators, so no site: templates here.
DEMAND = ['{problem} "I wish there was"', '{problem} frustrated OR annoying OR "hate"']
# Competitors keep the topic: every query names the problem (lint enforces it). The audience is added only when
# it narrows the search ("everyone" would turn the query into a generic product search).
COMPETITORS = ["{problem} {product_type}", "best {product_type} for {problem} {year}"]
COMPETITORS_AUDIENCE = "{product_type} for {audience} {problem}"
GENERIC_AUDIENCE = re.compile(r"^(everyone|everybody|anyone|anybody|people|all|users|someone|the public|general public)"
                              r"(\b.*)?$", re.I)
STOPWORDS = {"the", "and", "for", "with", "a", "an", "of", "to", "in", "on", "my", "your", "their", "not"}
SECOND_PASS = ["alternatives to {competitor}"]
PRICING = ["{competitor} pricing"]
PRICING_FALLBACK = "{competitor} price per month"

COPY_WINDOW = 6
PLAIN_BANNED = re.compile(r"\b(forum|forums|discussion|discussions)\b", re.I)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\"'`/]", " ", s or "")).strip()


def competitor_name(name: str) -> str:
    """A competitor name read from a web page: letters, digits and spaces only, at most 4 words."""
    words = re.sub(r"[^\w\s.&+-]", " ", name or "").split()
    return " ".join(words[:4]) if words and len(words) <= 4 else ""


def _fill(template: str, **kw: str) -> str:
    return re.sub(r"\s+", " ", template.format(**kw)).strip()


def _dedupe_words(query: str) -> str:
    """'to-do list to-do list templates' -> 'to-do list templates' (problem and product type often overlap)."""
    seen: set[str] = set()
    out = []
    for w in query.split():
        k = w.lower()
        if k in seen and k not in ("for",):
            continue
        seen.add(k)
        out.append(w)
    q = " ".join(out)
    return re.sub(r"\bfor\s+(?=(\d{4})?$)", "", q).strip()


def keywords(phrase: str) -> set[str]:
    """Content words of a phrase, hyphens dropped ("to-do list" -> {"todo", "list"})."""
    words = re.findall(r"[\w-]+", (phrase or "").lower())
    return {w.replace("-", "") for w in words if w not in STOPWORDS and len(w.replace("-", "")) >= 3}


def names_problem(query: str, terms: SearchTerms) -> bool:
    q = keywords(query)
    return any(keywords(p) & q for p in [terms.problem, *terms.synonyms] if p)


def generic_audience(audience: str) -> bool:
    a = _clean(audience)
    return not a or bool(GENERIC_AUDIENCE.match(a)) or a.lower().startswith(("everyone ", "anyone ", "people "))


def lint(query: str, idea: str = "", year: Optional[int] = None, *, purpose: str = "",
         terms: Optional[SearchTerms] = None) -> Optional[str]:
    """Return why a query is rejected, or None if it may be sent."""
    year = year or datetime.now().year
    if purpose == "competitors" and terms is not None and not names_problem(query, terms):
        return "competitor query does not name the problem keyword or a synonym"
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
        out = [_fill(t, product_type=product, problem=problem, year=year) for t in COMPETITORS]
        if not generic_audience(audience):
            out.append(_fill(COMPETITORS_AUDIENCE, product_type=product, audience=audience, problem=problem))
        out = [_dedupe_words(q) for q in out]
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
