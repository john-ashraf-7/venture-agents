"""SIMULATED order events. This module contains NO payment code: no SDK, no card data, no money.

In the real design, checkout happens in the founder's OWN payment provider; its order webhook
would land here. In this prototype a button creates a SIMULATED `order_received` event.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.models import now_iso
from app.services import decision_log
from app.services.storage import kv_get, kv_set

LABEL = "SIMULATED"


def simulate_order_received(run_id: str, tier_name: str, price_usd: float) -> dict[str, Any]:
    order = {"order_id": "sim_" + uuid.uuid4().hex[:8], "label": LABEL, "event": "order_received", "tier": tier_name,
             "list_price_usd": price_usd, "money_moved": False, "created_at": now_iso(),
             "note": "SIMULATED event; no payment provider, no money."}
    orders = kv_get(run_id, "orders", [])
    orders.append(order)
    kv_set(run_id, "orders", orders)
    decision_log.append(run_id, "commerce", "simulated_order_received", label=LABEL, order_id=order["order_id"])
    log_line(run_id, f"order_received {order['order_id']} tier={tier_name} list_price=${price_usd:.2f} ({LABEL}, no money moved)")
    return order


def log_line(run_id: str, text: str) -> None:
    p = decision_log.run_dir(run_id) / "payment_test_log.md"
    if not p.exists():
        p.write_text("# Payment and delivery test log (SIMULATED / MOCKED)\n\n"
                     "No payment code exists in this system. Orders below are SIMULATED events; deliveries and "
                     "refund handling are MOCKED. No money was charged, held, moved or refunded.\n\n", encoding="utf-8")
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"- {now_iso()} {text}\n")
