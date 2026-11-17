# Gate: desk_evidence

**Recommendation: STOP.**

- Verdict computed by code: **STOP**
- Computed at: 2026-11-17T18:27:30Z

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
| demand_signals | 1 | >= 3 | False |
| paying_competitors | 0 | >= 1 | False |
| direct_competitors | 0 | <= 4 | True |
| blocking_compliance_flags | 0 | <= 0 | True |
| founder_fit | high-end cost $80 > budget $50; high-end effort 16 h > 4 h available; missing skills: graphic design, productivity research, basic marketing | high end within budget/time; skills covered | False |

## Explanation

Recommendation: STOP.
The gate evaluation found only 1 verified demand signal, below the required minimum of 3. No paying competitors were identified, and the founder’s cost and effort estimates exceed the available budget and time. Additionally, essential skills such as graphic design, productivity research, and basic marketing are missing. These failures trigger the STOP verdict according to the locked rule.

## Devil's advocate

- Bull case: Despite only having one demand signal, this venture still has the potential to fill a niche market need, as the direct competitors are limited, and there are no compliance issues.
- Bear case: The venture is at risk of failing due to the lack of multiple demand signals, which is a critical threshold, and the founder's current skill set is not fully aligned with the required efforts, especially in areas like graphic design and marketing.

## Options

- **STOP** (recommended): Stop this idea and write the STOP memo. Evidence: Only 1 verified demand signal(s); the locked minimum is 3.. Risk: May drop an idea that a different segment would want.
- **PIVOT_BACK**: Go back to Discover with a narrower niche. Evidence: Weak demand suggests re-scoping. Risk: Costs another research cycle.
- **GO** (weakest evidence): Override and continue anyway (typed reason required). Evidence: Contradicts the locked threshold. Risk: Builds on unproven demand.

## Founder decision

- Choice: **STOP** (recommendation was STOP)
- Override: False
- Reason: Weak evidence: 1 demand signal, no priced competitor, over budget and time
- Decided at: 2026-11-17T18:29:15Z
