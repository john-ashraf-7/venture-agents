# Tavily vs SearXNG: Phase 1 search health (2026-11-17)

Same three briefs, one run each per provider, `python -m evals.search_health`. Raw results:
`search_tavily.json` (Tavily, `SEARCH_PROVIDER=tavily`) and `search_searxng_2026-11-17.json` (SearXNG, run at the
same time). Each provider used an empty search cache, so every query was live. Both runs shared one GPU with each
other and with other jobs, so Phase 1 times are only roughly comparable.

| Brief | Provider | Queries | Distinct result domains | Community-site results | Pages read | Fetch failures | Demand signals at gate | Paying competitors | Gate verdict | Phase 1 time |
|---|---|---|---|---|---|---|---|---|---|---|
| invoice_templates | SearXNG | 6 | 21 | 2 | 5 | 2 | 0 | 0 | STOP | 42 s |
| invoice_templates | Tavily | 8 | 25 | 10 | 10 | 3 (Reddit bot wall) | 0 | 0 | STOP | 118 s |
| arabic_tutoring_guide | SearXNG | 8 | 19 | 3 | 10 | 4 (3 Reddit bot wall) | 0 | 0 | STOP | 87 s |
| arabic_tutoring_guide | Tavily | 6 | 12 | 6 | 5 | 4 (Reddit bot wall) | 0 | 0 | STOP | 84 s |
| excel_budget_small_ngo | SearXNG | 6 | 17 | 6 | 5 | 2 | 0 | 0 | STOP | 56 s |
| excel_budget_small_ngo | Tavily | 8 | 14 | 9 | 10 | 6 (4 Reddit bot wall) | 0 | 0 | STOP | 124 s |

- Engines: SearXNG had 2-6 engines answering per brief, with duckduckgo (CAPTCHA), mojeek and qwant (access denied)
  failing. Tavily answered 21 of 22 queries (1 read timeout).
- Tavily credits used: about 22 (21 answered "basic" searches plus 1 timeout), out of a free tier of about 1,000 a month.
- Community-site results: Tavily returned 25 vs SearXNG's 11, because demand queries are limited to the gate's
  community domains. Most of them are Reddit threads, which block direct page fetches from this IP, so none
  became a counted demand signal.
- Paying competitors and gate verdicts are the same for both providers. On these three briefs the bottleneck is
  page fetching (Reddit bot wall) and price verification, not search.

Recommendation: Tavily is not "way better" on these numbers. It is a more reliable search source (no
CAPTCHA or suspended engines) and finds more forum threads, so it is worth keeping as an optional provider, used
automatically when the founder adds their own free key and falling back to SearXNG for each query otherwise.
It does not change any gate outcome unless the forum threads it finds can be read.
