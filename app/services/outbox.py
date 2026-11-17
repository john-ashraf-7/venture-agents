"""Outbox: the ONLY path from the system to the outside world.

Tier 0 internal  (drafts, writing to outputs/)            -> automatic
Tier 1 outward   (publish, send, post, serve landing page) -> founder approval, one by one; MOCKED connectors
Tier 2 forbidden (payments, refunds, transfers, credentials) -> always blocked

Any recipient / URL / publish target whose provenance is `web` is rejected: text from a web page
can never choose where something goes.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from app.models import Provenance, now_iso
from app.services import decision_log, events, guard
from app.services.storage import conn, kv_set

TIER0 = {"write_output"}
TIER1 = {"publish_page", "serve_landing_page", "publish_store_page", "send_email", "post", "export_file", "send_support_reply"}
TIER2 = {"payment", "charge", "refund", "transfer", "payout", "store_credentials", "store_card"}


class OutboxRejected(RuntimeError):
    pass


def tier_of(kind: str) -> int:
    if kind in TIER2:
        return 2
    if kind in TIER1:
        return 1
    if kind in TIER0:
        return 0
    return 2  # unknown kinds are treated as forbidden (fail closed)


def _save(item: dict[str, Any]) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO outbox (id, run_id, tier, status, body) VALUES (?,?,?,?,?)",
                  (item["id"], item["run_id"], item["tier"], item["status"], json.dumps(item, default=str)))


def get(item_id: str) -> Optional[dict[str, Any]]:
    with conn() as c:
        row = c.execute("SELECT body FROM outbox WHERE id=?", (item_id,)).fetchone()
    return json.loads(row["body"]) if row else None


def items(run_id: Optional[str] = None, status: Optional[str] = None) -> list[dict[str, Any]]:
    q, args = "SELECT body FROM outbox", []
    clauses = []
    if run_id:
        clauses.append("run_id=?")
        args.append(run_id)
    if status:
        clauses.append("status=?")
        args.append(status)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    with conn() as c:
        rows = c.execute(q, args).fetchall()
    return sorted((json.loads(r["body"]) for r in rows), key=lambda x: x["created_at"])


def submit(run_id: str, kind: str, *, title: str, content: str, target: str = "local",
           target_provenance: Provenance = Provenance.founder, requested_by: str = "agent",
           meta: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Queue an outward action. Returns the stored item (status shows what happened)."""
    tier = tier_of(kind)
    item: dict[str, Any] = {
        "id": "ob_" + uuid.uuid4().hex[:10], "run_id": run_id, "kind": kind, "tier": tier, "title": title,
        "content": content, "target": target, "target_provenance": Provenance(target_provenance).value,
        "requested_by": requested_by, "created_at": now_iso(), "status": "pending_approval", "reason": "",
        "connector": "MOCKED", "meta": meta or {},
    }
    if events.KILL.is_set():
        item["status"], item["reason"] = "cancelled", "Kill switch is on."
    elif tier == 2:
        item["status"], item["reason"] = "blocked", "Tier 2 (money or credentials) is always blocked. The founder acts in their own accounts."
    elif Provenance(target_provenance) == Provenance.web:
        item["status"], item["reason"] = "rejected", "Target came from web content; web text can never choose a recipient, URL or publish target."
    else:
        g = guard.check(f"{title}\n{content}", run_id=run_id, context="outbox")
        if not g.allowed:
            item["status"], item["reason"] = "blocked", "Policy Guard: " + g.reason
        elif tier == 0:
            item["status"] = "done"
    _save(item)
    decision_log.append(run_id, "outbox", f"queue_{kind}", sources=[], model=None, cost=0, approved_by=None,
                        outbox_id=item["id"], tier=tier, status=item["status"], reason=item["reason"])
    events.emit(run_id, "outbox", f"Outbox: {title} -> {item['status']}", item_id=item["id"])
    return item


def approve(item_id: str, founder_note: str = "") -> dict[str, Any]:
    item = get(item_id)
    if not item:
        raise OutboxRejected("no such item")
    if item["status"] != "pending_approval":
        raise OutboxRejected(f"item is {item['status']}, cannot approve")
    if events.KILL.is_set():
        raise OutboxRejected("kill switch is on")
    item["status"] = "approved"
    item["approved_at"] = now_iso()
    _execute_mocked(item)
    item["status"] = "done"
    item["delivery"] = "MOCKED: nothing left this machine." if item["kind"] != "serve_landing_page" else "Served locally only."
    _save(item)
    decision_log.append(item["run_id"], "outbox", f"approve_{item['kind']}", approved_by="founder",
                        outbox_id=item_id, note=founder_note, connector="MOCKED")
    return item


def reject(item_id: str, reason: str = "") -> dict[str, Any]:
    item = get(item_id)
    if not item:
        raise OutboxRejected("no such item")
    item["status"], item["reason"] = "rejected", reason or "Rejected by founder."
    _save(item)
    decision_log.append(item["run_id"], "outbox", f"reject_{item['kind']}", approved_by="founder", outbox_id=item_id)
    return item


def cancel_all_pending() -> int:
    n = 0
    for it in items(status="pending_approval"):
        it["status"], it["reason"] = "cancelled", "Kill switch pressed."
        _save(it)
        decision_log.append(it["run_id"], "kill_switch", "cancel_outbox_item", outbox_id=it["id"])
        n += 1
    return n


def _execute_mocked(item: dict[str, Any]) -> None:
    """MOCKED connectors: record what would have happened, never contact the outside world."""
    from app.services.decision_log import run_dir
    if item["kind"] == "serve_landing_page":
        kv_set(item["run_id"], "landing_served", True)
    out = run_dir(item["run_id"]) / "outbox_mocked_deliveries.md"
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"\n## {item['title']} (MOCKED {item['kind']})\n- approved: {item.get('approved_at')}\n- target: {item['target']}\n\n")
        f.write(item["content"][:3000] + "\n")
