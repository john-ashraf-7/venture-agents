# Payment and delivery test log (MOCKED: simulated order, no money moved)

No payment code exists in this system. Orders below are MOCKED events; deliveries and refund handling are MOCKED. No money was charged, held, moved or refunded.

- 2026-11-17T20:20:18Z order_received sim_40da25d4 tier=Basic list_price=$49.00 (MOCKED, no money moved)
- 2026-11-17T20:20:18Z delivered sim_40da25d4 via local download token (MOCKED, no email sent)
- 2026-11-17T20:20:18Z delivery for sim_40da25d4 already exists -> idempotent, no second delivery
- 2026-11-17T20:20:18Z access revoked for sim_40da25d4 (MOCKED)
- 2026-11-17T20:20:18Z refund requested for sim_40da25d4: recorded, access revoked, draft reply prepared; no money moved
- 2026-11-17T20:20:18Z reconcile: {'orders': 1, 'delivered': 1, 'undelivered': [], 'refund_requests': 1, 'payments': "n/a (no payment code; founder's provider holds payment data)"}
