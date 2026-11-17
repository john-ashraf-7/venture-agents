"""MOCKED automatic delivery of the digital product. Idempotent per order id: a repeated
order event never creates a second delivery."""
from __future__ import annotations

import secrets
from typing import Any, Optional

from app.commerce.payments import log_line
from app.models import now_iso
from app.services import decision_log
from app.services.storage import kv_get, kv_set


def deliver(run_id: str, order_id: str) -> dict[str, Any]:
    deliveries: dict[str, Any] = kv_get(run_id, "deliveries", {})
    if order_id in deliveries:
        log_line(run_id, f"delivery for {order_id} already exists -> idempotent, no second delivery")
        return {**deliveries[order_id], "duplicate": True}
    d = {"order_id": order_id, "token": secrets.token_urlsafe(12), "active": True, "delivered_at": now_iso(),
         "label": "MOCKED", "url": f"/download/{run_id}/{{token}}", "email_sent": False}
    d["url"] = f"/download/{run_id}/{d['token']}"
    deliveries[order_id] = d
    kv_set(run_id, "deliveries", deliveries)
    decision_log.append(run_id, "delivery", "mock_deliver_product", label="MOCKED", order_id=order_id)
    log_line(run_id, f"delivered {order_id} via local download token (MOCKED, no email sent)")
    return d


def revoke(run_id: str, order_id: str) -> Optional[dict[str, Any]]:
    deliveries: dict[str, Any] = kv_get(run_id, "deliveries", {})
    if order_id not in deliveries:
        return None
    deliveries[order_id]["active"] = False
    kv_set(run_id, "deliveries", deliveries)
    log_line(run_id, f"access revoked for {order_id} (MOCKED)")
    return deliveries[order_id]


def token_valid(run_id: str, token: str) -> bool:
    return any(d["token"] == token and d["active"] for d in kv_get(run_id, "deliveries", {}).values())
