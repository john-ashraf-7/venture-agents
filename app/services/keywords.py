"""Keyword check for the planner's SearchTerms (code, no model).

The buyer (audience) and product_type must come from the brief; problem and synonyms are the model's words for
the buyer's pain. Each checked content word
must appear in the brief or be a close variant of a brief word (same simple lemma, or fuzzy ratio
>= 0.85). The planner gets one corrective retry; anything still off-brief is replaced by a noun phrase
taken from the brief itself. Query templates (app/services/search/queries.py) are not touched here.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from app.models import Brief, SearchTerms

FUZZY = 0.85
STOP = set("""a an and are as at be but by can do for from get gets got has have how i in into is it its me my
need needs no not of on or our so that the their them they this to too up us use using want wants was we
what when where which who whom why will with without you your yours ones one who's""".split())


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"\w+", (text or "").lower()) if not w.isdigit()]


def lemma(w: str) -> str:
    """Crude English lemma, enough for plural/verb-form variants (payments -> payment, invoicing -> invoic)."""
    for suf, rep in (("ies", "y"), ("ing", ""), ("ers", "er"), ("es", ""), ("ed", ""), ("s", "")):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)] + rep
    return w


def brief_text(brief: Brief) -> str:
    return " ".join([brief.idea, brief.product_type, brief.target_market, " ".join(brief.skills)])


def _word_ok(w: str, vocab: set[str], lemmas: set[str]) -> bool:
    if w in STOP or w in vocab or lemma(w) in lemmas:
        return True
    return any(SequenceMatcher(None, w, v).ratio() >= FUZZY for v in vocab if abs(len(v) - len(w)) <= 3)


def off_brief(term: str, brief: Brief) -> bool:
    vocab = set(_words(brief_text(brief)))
    lemmas = {lemma(v) for v in vocab}
    content = [w for w in _words(term) if w not in STOP]
    return not content or not all(_word_ok(w, vocab, lemmas) for w in content)


def off_brief_terms(terms: SearchTerms, brief: Brief) -> list[str]:
    # problem and synonyms are the model's call (the buyer's pain in their own words, often not in the brief);
    # the buyer and the product type must come from the brief
    values = [terms.audience, terms.product_type]
    return [v for v in values if off_brief(v, brief)]


def check_message(brief: Brief):
    """A `check=` hook for llm.call: None when every keyword comes from the brief."""
    def _check(plan) -> Optional[str]:
        bad = off_brief_terms(plan.search_terms, brief)
        if not bad:
            return None
        return ("These search_terms use words that are not in the brief: " + ", ".join(repr(b) for b in bad)
                + ". Use the brief's own words (or a plural/verb form of them) for audience and product_type.")
    return _check


def noun_phrases(text: str, max_words: int = 4) -> list[str]:
    """Runs of content words between stopwords/punctuation: a cheap noun-phrase chunker."""
    out: list[str] = []
    for chunk in re.split(r"[^\w\s]|\n", (text or "").lower()):
        run: list[str] = []
        for w in chunk.split() + [""]:
            if w and w not in STOP and not w.isdigit():
                run.append(w)
                continue
            if run:
                out.append(" ".join(run[:max_words]))
            run = []
    seen: set[str] = set()
    return [p for p in out if not (p in seen or seen.add(p))]


def fallback(terms: SearchTerms, brief: Brief) -> tuple[SearchTerms, list[str]]:
    """Replace each off-brief keyword with a brief noun phrase. Returns (terms, replaced values)."""
    idea_np = noun_phrases(brief.idea)
    market_np = noun_phrases(brief.target_market)
    type_np = noun_phrases(brief.product_type)
    replaced: list[str] = []

    def pick(value: str, options: list[str]) -> str:
        if not off_brief(value, brief):
            return value
        replaced.append(value)
        return next((o for o in options if o), value)

    problem = terms.problem or next(iter(sorted(idea_np, key=len, reverse=True)), "")
    audience = pick(terms.audience, market_np + idea_np)
    product_type = pick(terms.product_type, type_np + idea_np)
    synonyms = list(terms.synonyms)
    for np_ in idea_np:
        if len(synonyms) >= len(terms.synonyms) or len(synonyms) >= 3:
            break
        if np_ not in (problem, audience, product_type) and np_ not in synonyms:
            synonyms.append(np_)
    return SearchTerms(problem=problem, audience=audience, product_type=product_type, synonyms=synonyms), replaced
