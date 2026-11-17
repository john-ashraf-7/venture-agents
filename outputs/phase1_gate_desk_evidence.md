# Gate: desk_evidence

**Recommendation: PARK.**

- Verdict computed by code: **PARK**
- Computed at: 2026-11-17T21:25:01Z

## Locked rule

```json
{
 "demand_signals_min": 1,
 "paying_competitors_min": 1,
 "direct_competitors_max": 4,
 "blocking_compliance_flags_max": 0,
 "founder_fit": {
  "compare": "high_end_of_estimate",
  "require_skills": true
 },
 "community_domains": [
  "reddit.com",
  "news.ycombinator.com",
  "stackexchange.com",
  "stackoverflow.com",
  "superuser.com",
  "askubuntu.com",
  "indiehackers.com",
  "producthunt.com/discussions",
  "quora.com",
  "techcommunity.microsoft.com"
 ],
 "demand_judged_by": "llm",
 "coverage_min": {
  "pages_read": 5,
  "verifiable_sources": 1
 },
 "counts_only": {
  "labels": [
   "SUPPORTED"
  ],
  "checked_by_different_family": true
 },
 "change_our_mind": "We would change the recommendation if at least 1 dated, sourced demand signals and 1 competitor with a verified public price were found, with no blocking compliance flag and a plan that fits the founder's budget and time.",
 "definitions": {
  "demand_signal": "A SUPPORTED claim, backed by a fetched source, of one of: a first-person problem statement with a date, on a site in community_domains (articles, template galleries and vendor blogs never count); an existing paid product with a public pricing page; a sourced trend whose quote contains a figure or date (at most one trend counts). Search-snippet claims are PARTIAL and never count.",
  "paying_competitor": "A competitor whose price was read from its own fetched page and verified by the claim checker.",
  "direct_competitor": "Same buyer, same job, same channel as the founder's idea.",
  "blocking_compliance_flag": "The idea falls in an excluded category (physical goods, financial/crypto, health or legal advice) or needs a licence the founder does not have."
 },
 "brief_idea": "A pack of payment-reminder email templates and an invoicing checklist for new freelancers",
 "counting": "distinct (source_url, type) SUPPORTED claims of types demand_signal, paying_competitor, trend, checked by a different model family"
}
```

## Checks

| check | value | threshold | pass |
|---|---|---|---|
| demand_signals | 1 | >= 1 | True |
| paying_competitors | 0 | >= 1 | False |
| direct_competitors | 1 | <= 4 | True |
| blocking_compliance_flags | 0 | <= 0 | True |
| founder_fit | high-end effort 60 h > 48 h available | high end within budget/time; skills covered | False |

## Explanation

Recommendation: PARK.
The gate evaluation found that while there is at least one demand signal, there are no paying competitors with a verified price, which is a required condition. The rule also requires a high-end founder fit within budget and time, but the founder’s effort estimate exceeds the available hours. Because these two key criteria are not met, the system recommends parking the idea. No other factors override this decision.

## Devil's advocate

- Bull case: The product fills a niche gap with unique features, and the demand signals indicate a clear need among the target audience, suggesting a viable market opportunity.
- Bear case: The absence of paying competitors and the unproven willingness to pay make it uncertain whether the product can generate sufficient revenue, potentially leading to financial difficulties.

## Options

- **PARK** (recommended): Pause; collect the missing evidence first. Evidence: No competitor with a verified price: willingness to pay is unproven.. Risk: Momentum loss.
- **PIVOT_BACK**: Re-scope the idea. Evidence: Partial evidence. Risk: Another research cycle.
- **GO** (weakest evidence): Override and continue anyway (typed reason required). Evidence: Below the locked threshold. Risk: Builds on unproven demand.

## Founder decision

- Choice: **GO** (recommendation was PARK)
- Override: True
- Reason: Demo run to show the full pipeline; the system recommended PARK (no priced competitor, 60 h > 48 h)
- Decided at: 2026-11-17T21:26:01Z
