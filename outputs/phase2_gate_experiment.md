# Gate: experiment

**Recommendation: REPEAT.**

- Verdict computed by code: **REPEAT** (state: IN_PROGRESS)
- Computed at: 2026-11-17T20:13:00Z

## Locked rule

```json
{
 "benchmark_claim_id": null,
 "change_our_mind": "If fewer than 100 sign\u2011ups occur, we should conclude the templates are not compelling enough and reconsider the product offering or pricing before investing further.",
 "excluded_sources": [
  "demo_audience",
  "simulated"
 ],
 "min_visitors": 500,
 "signups_threshold": 100,
 "threshold_source": "ASSUMPTION",
 "verdict_mapping": ">= threshold: GO; < 25% of threshold: STOP; otherwise PIVOT_BACK; no verdict before the window closes; INSUFFICIENT_SAMPLE below min_visitors",
 "window_days": 14
}
```

## Checks

| check | value | threshold | pass |
|---|---|---|---|
| signups_counted | 0 | >= 100 | None |
| visitors | 0 | >= 500 | False |

## Explanation

Recommendation: REPEAT.
The gate has evaluated the experiment and determined that the current data does not meet the minimum visitor threshold of 500, resulting in an INSUFFICIENT_SAMPLE status. Because the number of sign‑ups is below the required 100 threshold, the rule dictates a REPEAT verdict, meaning the experiment should be repeated with more data. The decision is based on the locked rule’s mapping, which specifies that when visitors are below the minimum, the verdict is INSUFFICIENT_SAMPLE, leading to a repeat. No further action is recommended until the required sample size is achieved.

## Devil's advocate

- Bull case: Despite low current engagement, the platform could gain traction quickly with targeted marketing and user-friendly design, attracting more visitors and sign-ups in the coming weeks.
- Bear case: Given the lack of initial visitors and sign-ups, the product may struggle to attract a user base, making it difficult to achieve the necessary scale for success.

## Options

- **REPEAT** (recommended): Repeat / check again later. Evidence: 0 sign-ups, day 1 of 14, too early to judge.. Risk: Time.
- **PARK**: Pause. Evidence: Not addressed. Risk: Delay.
- **GO** (weakest evidence): Override and continue without a verdict (typed reason required). Evidence: No verdict yet. Risk: Builds on unmeasured demand.

## Founder decision

- Choice: **GO** (recommendation was REPEAT)
- Override: True
- Reason: Demo run: proceeding to Build before the experiment window closes; no sign-up evidence yet
- Decided at: 2026-11-17T20:13:34Z
