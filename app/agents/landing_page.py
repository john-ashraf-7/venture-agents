"""Landing Page builder: copy from the copywriter role; HTML (with a real waitlist form) rendered by code.
The form stores only email + timestamp, shows a consent line, and offers a delete link.
No countdowns, no fake counts, no testimonials."""
from __future__ import annotations

import html

from app.agents import base
from app.models import Brief, ExperimentPlan, LandingCopy, LeanCanvas


def copy(run_id: str, brief: Brief, canvas: LeanCanvas, plan: ExperimentPlan) -> LandingCopy:
    return base.run(run_id, "landing_page", "copywriter", "write_landing_copy", LandingCopy,
                    {"value_proposition": [i.text for i in canvas.unique_value_proposition],
                     "problem": [i.text for i in canvas.problem], "customer": [i.text for i in canvas.customer_segments],
                     "hypothesis": plan.hypothesis},
                    instructions="Write honest waitlist landing copy. No reviews, testimonials, user counts, urgency, "
                                 "income promises or other brands' names.")


def render(run_id: str, c: LandingCopy) -> str:
    e = html.escape
    bullets = "".join(f"<li>{e(b)}</li>" for b in c.bullets)
    faq = "".join(f"<dt>{e(f.q)}</dt><dd>{e(f.a)}</dd>" for f in c.faq)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(c.headline)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:2rem auto;padding:0 1rem;line-height:1.5}}
form{{display:flex;gap:.5rem;flex-wrap:wrap}}input[type=email]{{flex:1;padding:.6rem}}button{{padding:.6rem 1rem}}
.small{{font-size:.85rem;color:#555}}.badge{{background:#fde68a;padding:.1rem .4rem;border-radius:4px;font-size:.8rem}}</style>
</head><body>
<p class="badge">Waitlist test - this product does not exist yet</p>
<h1>{e(c.headline)}</h1>
<p>{e(c.subheadline)}</p>
<ul>{bullets}</ul>
<form method="post" action="/lp/{run_id}/signup">
  <input type="email" name="email" required placeholder="you@example.com" aria-label="Email">
  <input type="hidden" name="src" value="">
  <button type="submit">{e(c.cta)}</button>
</form>
<p class="small">We store only your email address and the time you signed up, to tell you if this launches.
No other data, no sharing. <a href="/lp/{run_id}/delete">Delete my email</a>.</p>
<dl>{faq}</dl>
<script>const s=new URLSearchParams(location.search).get('src');if(s)document.querySelector('input[name=src]').value=s;</script>
</body></html>"""
