# Research plan (fixed before any web page was read)

- Effort estimate (ASSUMPTION): 5-10 hours (available: 4.0)
- Cost estimate (ASSUMPTION): $0-$50 (budget: 50.0)
- Baseline used (ASSUMPTION, config/product_type_baselines.yaml): Template pack / guide / checklist: 10-40 hours, $0-$150
- Model's own estimate (ASSUMPTION): 4-10 hours, $0-$50; adjustment reason: Limited time availability reduces effort
- Clamped in code: yes (allowed 5-60 hours, $0-$225)
- Required skills (ASSUMPTION): 
- Founder capacity: TIGHT - scope reduced and guardrails tightened
- Caps (demo-fast): {'results_per_query': 5, 'max_queries': 3, 'max_pages': 5, 'page_chars': 6000, 'demand_queries': 4, 'competitor_queries': 2, 'pricing_queries': 2}

## Search terms (keywords from the planner)

```json
{
 "problem": "generic to-do list template pack",
 "audience": "everyone who wants to be productive",
 "product_type": "template pack",
 "synonyms": [
  "generic to-do list",
  "to-do list template pack"
 ]
}
```

## Queries (built in code from templates, linted)

- [demand] generic to-do list "I wish there was"
- [demand] generic to-do list frustrated OR annoying OR "hate"
- [competitors] best template pack for generic to-do list 2026

Second-pass queries (`alternatives to` / `pricing` for the first competitor found) are added after reading and logged in the decision log with the competitor name's web provenance.

## Lessons from earlier runs (relevance-filtered)

- Over half of extracted claims were unsupported for 'Another generic to-do list template pack for everyone'; prefer pages with explicit prices and dated posts.