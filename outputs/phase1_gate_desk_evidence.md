# Gate: desk_evidence

**Recommendation: PARK.**

- Verdict computed by code: **PARK**
- Computed at: 2026-11-17T20:10:09Z

## Locked rule

```json
{
 "demand_signals_min": 3,
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
 "counts_only": {
  "labels": [
   "SUPPORTED"
  ],
  "checked_by_different_family": true
 },
 "change_our_mind": "We would change the recommendation if at least 3 dated, sourced demand signals and 1 competitor with a verified public price were found, with no blocking compliance flag and a plan that fits the founder's budget and time.",
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
| demand_signals | 2 | >= 3 | False |
| paying_competitors | 1 | >= 1 | True |
| direct_competitors | 9 | <= 4 | False |
| blocking_compliance_flags | 0 | <= 0 | True |
| founder_fit | high-end cost $600 > budget $300; high-end effort 60 h > 48 h available | high end within budget/time; skills covered | False |

## Explanation

Recommendation: PARK.
The decision is based on the locked rule that requires at least 3 verified demand signals, but only 2 were found. Additionally, there are 9 direct competitors, exceeding the maximum of 4 allowed. The founder fit also fails because the high-end cost and effort exceed the budget and available time. No other criteria were violated, but these failures are sufficient for a PARK verdict.

## Devil's advocate

- Bull case: The presence of at least one paying competitor indicates that there is a market willing to pay for this product, suggesting potential revenue opportunities.
- Bear case: The lack of sufficient demand signals and the high number of direct competitors imply that there might be insufficient interest and difficulty in standing out, which could lead to low adoption rates.

## Options

- **PARK** (recommended): Pause; collect the missing evidence first. Evidence: 2 verified demand signals, below the locked minimum of 3.. Risk: Momentum loss.
- **PIVOT_BACK**: Re-scope the idea. Evidence: Partial evidence. Risk: Another research cycle.
- **GO** (weakest evidence): Override and continue anyway (typed reason required). Evidence: Below the locked threshold. Risk: Builds on unproven demand.

## Founder decision

- Choice: **GO** (recommendation was PARK)
- Override: True
- Reason: Demo run to show the full pipeline; evidence is weak (2/3 demand, 9 direct competitors) and the system recommended PARK
- Decided at: 2026-11-17T20:12:18Z
