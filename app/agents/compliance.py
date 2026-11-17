"""Compliance: quick check in Phase 1, full checklist with official sources in Phase 4.
Not legal advice: every output says to confirm with a lawyer.
"""
from __future__ import annotations

from app.agents import base
from app.config import load_yaml
from app.models import Brief, ComplianceChecklist, ComplianceFlag, ComplianceQuick
from app.services import guard

DISCLAIMER = "Not legal advice - confirm with a lawyer in your jurisdiction."


def quick(run_id: str, brief: Brief) -> ComplianceQuick:
    res = base.run(run_id, "compliance", "analyst", "compliance_quick_check", ComplianceQuick,
                   {"brief": brief},
                   instructions="List compliance issues for selling this as a digital product (privacy/GDPR, consumer "
                                "law, platform rules). blocking=true only if the product is in an excluded category "
                                "(physical goods; financial/investment/crypto; health or medical advice; legal advice) "
                                "or needs a licence the founder lacks.")
    excluded = guard.excluded_type(f"{brief.idea} {brief.product_type}")
    if excluded and not any(f.blocking for f in res.flags):
        res.flags.append(ComplianceFlag(issue=f"Excluded product type: {excluded}", blocking=True,
                                        reason="Detected by code rule (app/services/guard.py)."))
    return res


def sources() -> list[dict[str, str]]:
    return load_yaml("compliance_sources.yaml").get("sources", [])


def checklist(run_id: str, brief: Brief, product_title: str) -> ComplianceChecklist:
    srcs = sources()
    res = base.run(run_id, "compliance", "analyst", "compliance_full_checklist", ComplianceChecklist,
                   {"brief": brief, "product": product_title, "official_sources": srcs},
                   sources=[s["url"] for s in srcs],
                   instructions="Write a checklist for selling this digital product. Each item must cite source_id "
                                "from official_sources. " + DISCLAIMER)
    valid = {s["id"] for s in srcs}
    for item in res.items:
        if item.source_id not in valid:
            item.note = "ASSUMPTION (no official source matched): " + item.note
            item.source_id = "ASSUMPTION"
    return res
