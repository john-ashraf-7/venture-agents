# Payment and delivery test log (MOCKED: simulated order, no money moved)

No payment code exists in this system. Orders below are MOCKED events; deliveries and refund handling are MOCKED. No money was charged, held, moved or refunded.

- 2026-11-17T21:27:38Z order_received sim_3bd1434c tier=Basic list_price=$29.99 (MOCKED, no money moved)
- 2026-11-17T21:27:38Z delivered sim_3bd1434c via local download token (MOCKED, no email sent)
- 2026-11-17T21:27:38Z delivery for sim_3bd1434c already exists -> idempotent, no second delivery
- 2026-11-17T21:27:38Z access revoked for sim_3bd1434c (MOCKED)
- 2026-11-17T21:27:38Z refund requested for sim_3bd1434c: recorded, access revoked, draft reply prepared; no money moved
- 2026-11-17T21:27:38Z reconcile: {'orders': 1, 'delivered': 1, 'undelivered': [], 'refund_requests': 1, 'payments': "n/a (no payment code; founder's provider holds payment data)"}
