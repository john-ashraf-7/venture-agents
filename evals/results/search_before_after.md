# Search health: before → after (Steps 1-3)

Before: `search_baseline.json` (commit 8c92742). After: `search_after.json`. Same three briefs, demo-fast, RTX 3090, live SearXNG.

| brief | engines responding | distinct domains | pages read | pages failed | snippet sources | demand signals (community domains) | lint-rejected queries | Phase 1 time |
|---|---|---|---|---|---|---|---|---|
| invoice_templates | 1 → 6 | 7 → 32 | 5 → 18 | 3 → 12 | 0 → 12 | 0 (-) → 1 (-) | 0 → 0 | 45.3 s → 63.1 s |
| arabic_tutoring_guide | 2 → 3 | 7 → 25 | 5 → 14 | 3 → 8 | 0 → 10 | 1 (reddit.com) → 0 (-) | 0 → 0 | 38.5 s → 77.6 s |
| excel_budget_small_ngo | 2 → 6 | 12 → 19 | 5 → 10 | 2 → 8 | 0 → 6 | 0 (-) → 0 (-) | 0 → 0 | 26.2 s → 59.9 s |

Engines responding after: invoice_templates: bing, duckduckgo, google cse, mojeek, stackoverflow, superuser; arabic_tutoring_guide: bing, duckduckgo, google cse; excel_budget_small_ngo: askubuntu, bing, duckduckgo, google cse, stackoverflow, superuser

Unresponsive after: invoice_templates: duckduckgo: CAPTCHA, mojeek: Suspended: access denied, mojeek: access denied, qwant: Suspended: access denied, qwant: access denied, startpage: Suspended: CAPTCHA; arabic_tutoring_guide: duckduckgo: CAPTCHA, google cse: Suspended: too many requests, mojeek: Suspended: access denied, mojeek: access denied, qwant: Suspended: access denied, qwant: access denied, startpage: Suspended: CAPTCHA; excel_budget_small_ngo: duckduckgo: CAPTCHA, mojeek: Suspended: access denied, qwant: Suspended: access denied, startpage: Suspended: CAPTCHA

Fetch rejection reasons after: invoice_templates: {'timeout': 3, 'http_403': 4, 'too_short': 2, 'error_ConnectError': 1, 'bot_check': 2}; arabic_tutoring_guide: {'timeout': 4, 'http_404': 1, 'http_403': 3}; excel_budget_small_ngo: {'http_403': 7, 'timeout': 1}
