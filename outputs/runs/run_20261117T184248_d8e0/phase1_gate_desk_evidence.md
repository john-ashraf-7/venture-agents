# Gate: desk_evidence

**Recommendation: STOP.**

- Verdict computed by code: **STOP**
- Computed at: 2026-11-17T18:43:09Z

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
 "counts_only": {
  "labels": [
   "SUPPORTED"
  ],
  "checked_by_different_family": true
 },
 "change_our_mind": "We would change the recommendation if at least 3 dated, sourced demand signals and 1 competitor with a verified public price were found, with no blocking compliance flag and a plan that fits the founder's budget and time.",
 "definitions": {
  "demand_signal": "A SUPPORTED claim, backed by a fetched source, of one of: a dated forum/community post describing the problem; an existing paid product with a public pricing page; a sourced trend.",
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
| direct_competitors | 1 | <= 4 | True |
| blocking_compliance_flags | 0 | <= 0 | True |
| founder_fit | high-end cost $80 > budget $50; high-end effort 16 h > 4 h available; missing skills: graphic design, productivity research, basic marketing | high end within budget/time; skills covered | False |

## Explanation

Recommendation: STOP.
The gate evaluation found zero verified demand signals, falling short of the required minimum of three. No paying competitors were identified, and the founder’s fit assessment failed due to budget, time, and skill gaps. The other checks passed, but the unmet demand signal requirement alone triggers the STOP verdict. Therefore, the recommendation is to halt the idea at this stage.

## Devil's advocate

- Bull case: While there are currently no paying competitors, the project could still succeed by focusing on cost-effective strategies and leveraging the existing low direct competitor landscape to gain market share.
- Bear case: The project faces significant challenges as it currently lacks verified demand signals, which are a crucial indicator of market readiness, and the founder's budget and time constraints may hinder the project's ability to meet its goals.

## Options

- **STOP** (recommended): Stop this idea and write the STOP memo. Evidence: Only 0 verified demand signal(s); the locked minimum is 3.. Risk: May drop an idea that a different segment would want.
- **PIVOT_BACK**: Go back to Discover with a narrower niche. Evidence: Weak demand suggests re-scoping. Risk: Costs another research cycle.
- **GO** (weakest evidence): Override and continue anyway (typed reason required). Evidence: Contradicts the locked threshold. Risk: Builds on unproven demand.

## Founder decision

- Choice: **STOP** (recommendation was STOP)
- Override: False
- Reason: No forum demand signals, no priced competitor, over budget and time
- Decided at: 2026-11-17T18:43:25Z
