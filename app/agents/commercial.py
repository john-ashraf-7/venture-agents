"""Phase 4-6 writing agents: docs writer, pricing, policy drafter, store page, launch posts, support,
metrics analyst, memo writer. All return drafts; none can publish or send anything."""
from __future__ import annotations

from typing import Any

from app.agents import base
from app.models import (PRD, Brief, Claim, GuidePack, LaunchPosts, Label, LeanCanvas, MemoBody, MetricsReading,
                        PolicyDrafts, PricingSheet, StorePage, SupportDrafts, UserDocs)

NO_HYPE = ("Never promise income or results, never invent reviews, testimonials, user counts or urgency, never "
           "name or imitate other brands, never write as the founder's customers.")


def docs(run_id: str, pack: GuidePack) -> UserDocs:
    return base.run(run_id, "docs_writer", "copywriter", "write_user_docs", UserDocs,
                    {"product_title": pack.title, "sections": [s.heading for s in pack.sections],
                     "templates": [t.name for t in pack.templates]},
                    instructions="Write short user docs in Markdown: what is inside, how to use it, file formats "
                                 "(HTML + Markdown), how to get help.")


def pricing(run_id: str, brief: Brief, canvas: LeanCanvas, claims: list[Claim]) -> PricingSheet:
    prices = [{"id": c.id, "text": c.text, "url": c.source_url} for c in claims
              if c.type == "paying_competitor" and c.label == Label.SUPPORTED]
    sheet = base.run(run_id, "pricing", "analyst", "propose_pricing", PricingSheet,
                     {"brief": brief, "revenue_streams": [i.text for i in canvas.revenue_streams],
                      "verified_competitor_prices": prices},
                     instructions="Propose 1-3 one-time price tiers in USD with a rationale citing competitor claim ids. "
                                  "Core content must not be paywalled behind extra tiers. " + NO_HYPE)
    valid = {p["id"] for p in prices}
    sheet.competitor_claim_ids = [c for c in sheet.competitor_claim_ids if c in valid]
    return sheet


def policies(run_id: str, brief: Brief, product_title: str, sheet: PricingSheet) -> PolicyDrafts:
    return base.run(run_id, "policy_drafter", "copywriter", "draft_policies", PolicyDrafts,
                    {"product": product_title, "seller_values": brief.values, "pricing": sheet,
                     "data_collected": ["email address", "order id", "timestamp"]},
                    instructions="Draft terms of sale, privacy policy and refund policy in Markdown for a digital "
                                 "download. Start each with 'DRAFT - not legal advice - confirm with a lawyer.' "
                                 "State that payments are handled by the seller's own payment provider and that this "
                                 "system never stores card numbers or passwords.")


def store_page(run_id: str, pack: GuidePack, sheet: PricingSheet, canvas: LeanCanvas) -> StorePage:
    return base.run(run_id, "store_page", "copywriter", "write_store_page", StorePage,
                    {"product": pack.title, "contents": [s.heading for s in pack.sections],
                     "value_proposition": [i.text for i in canvas.unique_value_proposition],
                     "price_tiers": sheet.tiers},
                    instructions="Write an honest store page. Describe only what is in the product. " + NO_HYPE)


def launch_posts(run_id: str, page: StorePage, channels: list[str]) -> LaunchPosts:
    return base.run(run_id, "launch_post", "copywriter", "write_launch_posts", LaunchPosts,
                    {"store_page": page, "channels": channels},
                    instructions="Write one short launch post per channel, in the founder's own plain voice, for the "
                                 "founder to review and post themselves. " + NO_HYPE)


def support(run_id: str, tickets: list[dict[str, Any]], policies_: PolicyDrafts) -> SupportDrafts:
    return base.run(run_id, "support", "copywriter", "draft_support_replies", SupportDrafts,
                    {"tickets_MOCKED": tickets, "refund_policy_DRAFT": policies_.refund_md[:2500]},
                    instructions="Draft polite replies. Refunds: say the founder will review it; never promise or "
                                 "perform a refund. These are drafts for the founder.")


def metrics(run_id: str, data: dict[str, Any]) -> MetricsReading:
    return base.run(run_id, "metrics_analyst", "analyst", "read_metrics", MetricsReading,
                    {"metrics_MOCKED": data},
                    instructions="These metrics are MOCKED demo data. Describe what they would mean and list risks. "
                                 "Do not treat them as evidence.")


def memo(run_id: str, facts: dict[str, Any], recommendation: str) -> MemoBody:
    return base.run(run_id, "memo_writer", "analyst", "write_persevere_or_pivot_memo", MemoBody,
                    {"facts": facts, "recommendation_computed_by_code": recommendation},
                    instructions=f"Write a short persevere-or-pivot memo in Markdown. The first sentence must be "
                                 f"'Recommendation: {recommendation}.' Separate evidence (sourced) from ASSUMPTION "
                                 "and MOCKED data.")
