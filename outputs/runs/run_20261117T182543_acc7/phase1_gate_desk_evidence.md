# Gate: desk_evidence

**Recommendation: PARK.**

- Verdict computed by code: **PARK**
- Computed at: 2026-11-17T18:26:16Z

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
| demand_signals | 2 | >= 3 | False |
| paying_competitors | 0 | >= 1 | False |
| direct_competitors | 0 | <= 4 | True |
| blocking_compliance_flags | 0 | <= 0 | True |
| founder_fit | high-end cost $80 > budget $50; high-end effort 16 h > 4 h available; missing skills: graphic design, productivity research, basic marketing | high end within budget/time; skills covered | False |

## Explanation

Recommendation: PARK.
The gate evaluation found only 2 demand signals, which is below the required minimum of 3. No paying competitors were identified, and the founder’s cost and effort estimates exceed the budget and available time. Additionally, essential skills such as graphic design, productivity research, and basic marketing are missing. These unmet criteria trigger the PARK verdict according to the locked rule.

## Devil's advocate

- Bull case: Despite the lack of paying competitors and direct competition, the project has successfully identified a niche market with 2 verified demand signals, indicating potential for growth and profitability.
- Bear case: The project fails to meet the minimum demand signal threshold of 3, and the founder's budget and time constraints, along with missing key skills, significantly increase the risk of failure, making it difficult to achieve the necessary traction.

## Options

- **PARK** (recommended): Pause; collect the missing evidence first. Evidence: 2 verified demand signals, below the locked minimum of 3.. Risk: Momentum loss.
- **PIVOT_BACK**: Re-scope the idea. Evidence: Partial evidence. Risk: Another research cycle.
- **GO** (weakest evidence): Override and continue anyway (typed reason required). Evidence: Below the locked threshold. Risk: Builds on unproven demand.

## Timing

Intake to verdict: 32.8 s (demo-fast).
