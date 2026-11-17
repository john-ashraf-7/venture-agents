# Gate: desk_evidence

**Recommendation: STOP.**

- Verdict computed by code: **STOP**
- Computed at: 2026-11-17T21:04:54Z

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
 "change_our_mind": "We would change the recommendation if at least 3 dated, sourced demand signals and 1 competitor with a verified public price were found, with no blocking compliance flag and a plan that fits the founder's budget and time.",
 "definitions": {
  "demand_signal": "A SUPPORTED claim, backed by a fetched source, of one of: a first-person problem statement with a date, on a site in community_domains (articles, template galleries and vendor blogs never count); an existing paid product with a public pricing page; a sourced trend whose quote contains a figure or date (at most one trend counts). Search-snippet claims are PARTIAL and never count.",
  "paying_competitor": "A competitor whose price was read from its own fetched page and verified by the claim checker.",
  "direct_competitor": "Same buyer, same job, same channel as the founder's idea.",
  "blocking_compliance_flag": "The idea falls in an excluded category (physical goods, financial/crypto, health or legal advice) or needs a licence the founder does not have."
 },
 "brief_idea": "Another generic to-do list template pack for everyone",
 "counting": "distinct (source_url, type) SUPPORTED claims of types demand_signal, paying_competitor, trend, checked by a different model family"
}
```

## Checks

| check | value | threshold | pass |
|---|---|---|---|
| demand_signals | 0 | >= 3 | False |
| paying_competitors | 0 | >= 1 | False |
| direct_competitors | 4 | <= 4 | True |
| blocking_compliance_flags | 0 | <= 0 | True |
| founder_fit | high-end effort 10 h > 4 h available | high end within budget/time; skills covered | False |

## Explanation

Recommendation: STOP.
The verdict is based on the locked rule that requires at least 3 verified demand signals. Only 0 demand signals were found, falling short of the minimum threshold of 3. All other checks either passed or were not relevant to the stopping decision. Therefore, the system recommends stopping the idea. This recommendation is a direct result of the rule evaluation and not subject to interpretation.

## Devil's advocate

- Bull case: Despite the lack of direct paying competitors, the product can still succeed by offering unique features and solving a specific problem for its target market, potentially attracting early adopters and building a loyal user base.
- Bear case: The absence of demand signals and paying competitors suggests that the product may struggle to find traction, and the founder's high-end effort commitment may not be sustainable, risking the project's failure.

## Options

- **STOP** (recommended): Stop this idea and write the STOP memo. Evidence: Only 0 verified demand signal(s); the locked minimum is 3.. Risk: May drop an idea that a different segment would want.
- **PIVOT_BACK**: Go back to Discover with a narrower niche. Evidence: Weak demand suggests re-scoping. Risk: Costs another research cycle.
- **GO** (weakest evidence): Override and continue anyway (typed reason required). Evidence: Contradicts the locked threshold. Risk: Builds on unproven demand.

## Timing

Intake to verdict: 59.0 s (demo-fast).
