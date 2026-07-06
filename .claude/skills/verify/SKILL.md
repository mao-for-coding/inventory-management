---
name: verify
description: Verify changes to this app end-to-end by launching both servers and driving the real UI/API. Use before committing nontrivial changes.
---

# Verifying changes in inventory-management

## Launch

Both servers must run outside the Bash sandbox (they bind ports; the sandbox
also blocks localhost connections, so an in-sandbox `curl localhost` returns
000 even when a server is up — never trust that as "not running").

```bash
lsof -ti:3000,8001 | xargs kill -9 2>/dev/null   # clear ports (non-sandboxed)
cd server && uv run python main.py                # backend :8001, background
cd client && npm run dev                          # frontend :3000, background
curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/docs   # expect 200
```

The backend loads JSON from `server/data/` into memory at startup — restart it
after changing `server/*.py` or `server/data/*.json` (no auto-reload). Vite
hot-reloads the client. Restarting the backend resets all POSTed orders.

## Drive

- UI: browser tools against http://localhost:3000. Nav tabs: Overview,
  Inventory, Orders, Finance, Demand Forecast, Restocking, Reports.
- API: `curl` against http://localhost:8001/api/* (non-sandboxed).
- Restocking flow: /restocking → Place Order → banner with order number →
  /orders shows it in the "Submitted Orders" card.

## Gotchas

- The shared FilterBar (warehouse/category/status/month) drives most views;
  after adding fields or statuses, probe each filter — `apply_filters` in
  `server/main.py` lowercases string fields and crashes on None unless
  written as `(item.get(...) or '')`.
- Dates must be datetime strings (`YYYY-MM-DDTHH:MM:SS`); date-only strings
  parse as UTC midnight in JS and render a day early west of UTC.
- Order data is in-memory only; anything POSTed disappears on restart.
