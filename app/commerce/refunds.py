"""MOCKED refund handling: records the request, revokes the download token and drafts a reply.
The system never refunds money; only the founder can, in their own payment account."""
from __future__ import annotations

from typing import Any

from app.commerce import delivery
from app.commerce.payments import log_line
from app.models import now_iso
from app.services import decision_log
from app.services.storage import kv_get, kv_set


def request_refund(run_id: str, order_id: str, reason: str) -> dict[str, Any]:
    req = {"order_id": order_id, "reason": reason[:500], "requested_at": now_iso(), "label": "MOCKED",
           "money_moved": False,
           "draft_reply": ("Thanks for letting us know. Your refund request has been passed to the seller, who will "
                           "review it under the refund policy and reply personally."),
           "founder_action": "Review and, if appropriate, refund in your own payment provider account."}
    refunds = kv_get(run_id, "refunds", [])
    refunds.append(req)
    kv_set(run_id, "refunds", refunds)
    delivery.revoke(run_id, order_id)
    decision_log.append(run_id, "refunds", "record_refund_request", label="MOCKED", order_id=order_id)
    log_line(run_id, f"refund requested for {order_id}: recorded, access revoked, draft reply prepared; no money moved")
    return req


def reconcile(run_id: str) -> dict[str, Any]:
    """Match orders, deliveries and refunds (no payments/fees/payouts exist in the prototype)."""
    orders = kv_get(run_id, "orders", [])
    deliveries = kv_get(run_id, "deliveries", {})
    refunds = kv_get(run_id, "refunds", [])
    rep = {"orders": len(orders), "delivered": sum(1 for o in orders if o["order_id"] in deliveries),
           "undelivered": [o["order_id"] for o in orders if o["order_id"] not in deliveries],
           "refund_requests": len(refunds), "payments": "n/a (no payment code; founder's provider holds payment data)"}
    log_line(run_id, f"reconcile: {rep}")
    return rep
