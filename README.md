# MongoFleet — this drop

## Scope of this build

Your spec (25 sections, 20 platform services, real Paramiko/pymongo
execution) is a genuine multi-week enterprise build. This drop delivers a
**real, working foundation** — Phases 1–4 of your own implementation plan —
with zero mock data anywhere in what's included, plus the model/skeleton for
the operation engine so the next phase (real restart/upgrade/failover
execution) plugs straight in.

### What's real and working now
- `backend/` — Flask + PostgreSQL app: session-based auth, RBAC (roles,
  permissions, users — all DB-backed, no hardcoded accounts), inventory CRUD,
  **live** SSH connectivity test (Paramiko, allowlisted commands only) and
  **live** MongoDB health check (PyMongo — ping, serverStatus, replSetGetStatus),
  a dashboard-summary endpoint computed from real Postgres aggregates, and
  full audit logging on every write action.
- `frontend/login.html`, `frontend/dashboard.html`, `frontend/inventory.html`
  — rewired to call these real APIs (`assets/api.js`). All hardcoded rows
  (77 servers, fixed CPU%, fake alerts, canned "restart 64% complete") are
  gone, replaced with loading / empty / error states and whatever the
  backend actually returns. On a fresh install both pages correctly show
  "no servers registered yet" instead of fabricated numbers.

### Update: server-detail.html is now real too
`server-detail.html` no longer has any hardcoded fallback numbers (the old
"24.5%", "16 Cores", "Madan U (DBA Team)" placeholders are gone). It now
pulls from two distinct real sources — see `backend/deploy/README.md` →
"New in this drop":
- **Live metrics** (CPU/mem/disk/uptime/replication lag/connections) — fresh
  SSH + PyMongo pull on every page load, via
  `GET /api/inventory/servers/:id/live-metrics`.
- **Static inventory** (FQDN, OS, CPU cores, total memory/disk, Mongo
  version) — read from Postgres, written only by the new hourly cron job
  `scripts/collect_static_inventory.py`. A field with nothing collected yet
  shows "Unavailable" / "Not yet collected", never a fabricated value.

### What's still the original static mockup (untouched)
`operations.html`, `upgrade.html`, `failover-failback.html`,
`monitoring.html`, `governance.html` — these depend on services (operation
engine execution, config management, slow query analysis, index stats,
approvals) that aren't built yet. Wiring them to fake data would just move
the mock-data problem into a different file, so they're left as-is rather
than half-connected. They're the natural next phase — the `operations`
table and state machine fields already exist in `models.py` for exactly
this.

### Credentials
No password or secret key is hardcoded anywhere in this delivery — see
`backend/.env.example` and `backend/deploy/README.md`, including the note
about rotating the `appadmin` password and secret key that were pasted into
this chat.

## Next phase (recommended)
Phase 6–7 from your plan: the operation execution worker (state machine
REQUESTED → ... → SUCCESS) plus the real restart workflow, since DB Ops is
what you flagged as most important. That's a focused enough scope to do
properly in the next pass rather than thin-spreading across all 20 services
at once.
