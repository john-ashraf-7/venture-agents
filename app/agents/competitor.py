"""Competitor agent: builds the competitor table from page extracts (direct = same buyer, job, channel)."""
from __future__ import annotations

from typing import Any

from app.agents import base
from app.models import Brief, CompetitorTable


def run(run_id: str, brief: Brief, pages: list[dict[str, Any]]) -> CompetitorTable:
    products = [{"url": p["url"], "fields": p["extract"]} for p in pages
                if p["extract"].get("page_kind") == "product" or p["extract"].get("product_name")]
    if not products:
        return CompetitorTable(rows=[])
    return base.run(run_id, "competitor", "analyst", "build_competitor_table", CompetitorTable,
                    {"idea": brief.idea, "target_market": brief.target_market, "product_pages": products},
                    sources=[p["url"] for p in products],
                    instructions="One row per product found in these extracts only. url must be one of the given URLs. "
                                 "price_text only if it appears in the extract. is_direct=true only if same buyer, same job "
                                 "and same channel as the founder's idea.")
