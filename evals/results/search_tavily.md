# Tavily vs SearXNG: Phase 1 search results (2026-11-17)

Same three briefs, one run each per provider, `python -m evals.search_health`. Raw results:
`search_tavily.json` (Tavily, `SEARCH_PROVIDER=tavily`) and `search_searxng_2026-11-17.json` (SearXNG, run at the
same time). Each provider used an empty search cache, so every query was live. Both runs shared one GPU with each
other and with other jobs, so Phase 1 times are only roughly comparable.

## Search results (what came back per query)

Every returned URL was read by title and judged on-topic or not for its purpose (manual review of the URLs and
titles in the two runs' search logs; 5 results per query).

| Purpose | SearXNG | Tavily |
|---|---|---|
| Demand (12 queries each) | **0 of 56** results are on-topic community threads. `site:reddit.com` / `site:news.ycombinator.com` are ignored by the engines that answered, so results are PayPal, Kashier, CNN/BBC/NYT home pages, dictionary entries, Kahoot sign-in, zhihu/baidu, and unrelated Stack Overflow questions (WooCommerce email, Firefox cookies) | **about 38 of 41** are on-topic first-person threads: about 23 distinct ones on Reddit (r/Freelancers, r/learn_arabic, r/learnArabicSecular, r/nonprofit, r/grants), Indie Hackers, Hacker News, Quora and Product Hunt. Off-topic: 3 Quora pages matched on "wish"/"grant" |
| Competitors (6 queries each) | 20 of 30 on-topic; noise: Best Buy, WordReference, Cambridge Dictionary, a ChatGPT-jailbreak Reddit thread, zhihu | about 22 of 25 on-topic (template stores, Etsy, Airtable, Notion, Slidesgo); 1 query returned nothing |
| Pricing | 1 query (Tutor.com pricing): 5 of 5 on-topic, including the vendor's own pricing page | 2 queries: "Forge Invoice pricing" 0 of 5 (finance news about Forge Global), "NGO Templates Suite pricing" 1 of 5. The competitor names came from that run's extractor, so these differ from SearXNG's |
| Engine failures | duckduckgo (CAPTCHA), mojeek and qwant (access denied) on every brief | 1 read timeout in 22 queries |

## Pipeline numbers (for reference)

| Brief | Provider | Queries | Distinct result domains | Pages read | Fetch failures | Demand signals at gate | Gate verdict | Phase 1 time |
|---|---|---|---|---|---|---|---|---|
| invoice_templates | SearXNG | 6 | 21 | 5 | 2 | 0 | STOP | 42 s |
| invoice_templates | Tavily | 8 | 25 | 10 | 3 (Reddit bot wall) | 0 | STOP | 118 s |
| arabic_tutoring_guide | SearXNG | 8 | 19 | 10 | 4 (3 Reddit bot wall) | 0 | STOP | 87 s |
| arabic_tutoring_guide | Tavily | 6 | 12 | 5 | 4 (Reddit bot wall) | 0 | STOP | 84 s |
| excel_budget_small_ngo | SearXNG | 6 | 17 | 5 | 2 | 0 | STOP | 56 s |
| excel_budget_small_ngo | Tavily | 8 | 14 | 10 | 6 (4 Reddit bot wall) | 0 | STOP | 124 s |

Tavily credits used: about 22 (21 answered "basic" searches plus 1 timeout), out of a free tier of about 1,000 a month.

## Recommendation

On search results, Tavily is clearly better. For demand, the purpose the gate depends on, it returns relevant
first-person community threads where SearXNG returns none from this IP. Competitor results are cleaner too.
Pricing results depend on the competitor name the extractor picks, and were poor in both providers for vague
names. The gate outcome did not change because most of the threads Tavily finds are on Reddit, which blocks
direct page fetches from this IP. To turn these results into counted demand signals, the thread text has to be
read another way, for example Tavily's `include_raw_content` or Extract API. That is a separate change in the page reader.
