# Gate: desk_evidence

**Recommendation: PARK.**

- Verdict computed by code: **PARK**
- Computed at: 2026-11-17T18:25:35Z

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
 "brief_idea": "A pack of payment-reminder email templates and an invoicing checklist for new freelancers",
 "counting": "distinct (source_url, type) SUPPORTED claims of types demand_signal, paying_competitor, trend, checked by a different model family"
}
```

## Checks

| check | value | threshold | pass |
|---|---|---|---|
| demand_signals | 3 | >= 3 | True |
| paying_competitors | 0 | >= 1 | False |
| direct_competitors | 0 | <= 4 | True |
| blocking_compliance_flags | 0 | <= 0 | True |
| founder_fit | high-end effort 72 h > 48 h available | high end within budget/time; skills covered | False |

## Explanation

Recommendation: PARK.
The gate requires at least three demand signals, which are present. However, it also requires at least one paying competitor, and none were found. Additionally, the founder fit check failed because the effort estimate exceeds the available time. Therefore the verdict is to park the idea.

## Devil's advocate

- Bull case: The product has strong demand signals from 3 potential early adopters, indicating a clear market need and willingness to pay.
- Bear case: The absence of paying competitors suggests that the market may not be ready to pay for the product, and the lack of direct competitors could mean the idea is not valuable.

## Options

- **PARK** (recommended): Pause; collect the missing evidence first. Evidence: No competitor with a verified price: willingness to pay is unproven.. Risk: Momentum loss.
- **PIVOT_BACK**: Re-scope the idea. Evidence: Partial evidence. Risk: Another research cycle.
- **GO** (weakest evidence): Override and continue anyway (typed reason required). Evidence: Below the locked threshold. Risk: Builds on unproven demand.

## Timing

Intake to verdict: 64.0 s (demo-fast).
