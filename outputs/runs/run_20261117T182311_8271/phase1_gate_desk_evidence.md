# Gate: desk_evidence

**Recommendation: STOP.**

- Verdict computed by code: **STOP**
- Computed at: 2026-11-17T18:23:55Z

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
| demand_signals | 0 | >= 3 | False |
| paying_competitors | 0 | >= 1 | False |
| direct_competitors | 0 | <= 4 | True |
| blocking_compliance_flags | 0 | <= 0 | True |
| founder_fit | high-end effort 72 h > 48 h available | high end within budget/time; skills covered | False |

## Explanation

Recommendation: STOP.
The gate evaluation found 0 demand signals, falling short of the required minimum of 3. No paying competitors were identified, missing the threshold of at least 1. The founder fit check also failed, as the effort estimate exceeds the available time. These failures trigger the STOP verdict according to the locked rule.

## Devil's advocate

- Bull case: While there are currently no paying competitors, the project could attract early adopters and partnerships, which could eventually lead to a sustainable business model.
- Bear case: The absence of demand signals suggests that the market may not be ready for the product, which could lead to significant financial losses before any potential success.

## Options

- **STOP** (recommended): Stop this idea and write the STOP memo. Evidence: Only 0 verified demand signal(s); the locked minimum is 3.. Risk: May drop an idea that a different segment would want.
- **PIVOT_BACK**: Go back to Discover with a narrower niche. Evidence: Weak demand suggests re-scoping. Risk: Costs another research cycle.
- **GO** (weakest evidence): Override and continue anyway (typed reason required). Evidence: Contradicts the locked threshold. Risk: Builds on unproven demand.

## Timing

Intake to verdict: 43.4 s (demo-fast).
