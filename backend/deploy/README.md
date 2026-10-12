# MongoFleet backend — deployment guide (UAT/QA)

## Environment summary (this deployment)

- App runs as OS user **<app_service_user>**, under `/data/database-management`.
- MongoDB hosts are managed separately: custom install under OS user
  **<ssh_username>**, rooted at `/apps/DB/modb/` (`data/`, `log/`, `cfg/mongod.conf`),
  started via the `mongodb` systemd unit. `mongodump`/`mongoexport`/`mongosh`
  are on <ssh_username>'s PATH.
- App (<app_service_user>) reaches every MongoDB host over SSH as <ssh_username> — see
  section 2a for key setup.
- PostgreSQL (the app's own metadata DB) runs locally on the app server and
  is currently empty — section 1 below creates the role/database in it.

## 1. Create the platform DB in PostgreSQL

Run as whichever OS/Postgres account has rights to create roles/databases
on this instance (not necessarily <app_service_user>):

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE atlas_app WITH LOGIN PASSWORD 'REPLACE_ME';
CREATE DATABASE mongofleet OWNER atlas_app;
SQL
```

(If you already created `dbmgmt_db` / `dbmgmt_svc` from an earlier session,
that's fine too — just use those names consistently in `.env` `PG_DB`/`PG_USER`
below instead of `mongofleet`/`atlas_app`.)

Put the real password only in `.env` (`PG_PASSWORD=`), not here. If the
password contains `@`, `:`, `/` or similar characters, that's fine —
`config.py` URL-encodes it before building the connection string, so no
need to avoid special characters when generating it.

## 2. Python environment

```bash
su - <app_service_user>
cd /data/database-management/backend
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

If the app server has no internet access, download the wheels on a machine
that does (`pip download -r requirements.txt --platform manylinux2014_x86_64
--python-version 311 --implementation cp --abi cp311 --only-binary=:all: -d
offline_packages`), transfer the folder over, then on the server:
`pip install --no-index --find-links=./offline_packages -r requirements.txt`.

## 2a. SSH key from <app_service_user> (app) to <ssh_username> (every MongoDB host)

The SSH execution service and the slow-query log parser both connect as the
OS user configured in `.env` (`SSH_USER_NONPROD` / `SSH_USER_PROD`) — set
these to `<ssh_username>`. Generate one key pair per tier and copy it to every
MongoDB host:

```bash
su - <app_service_user>
ssh-keygen -t ed25519 -f ~/.ssh/<ssh_keyfile_nonprod> -N ""
ssh-copy-id -i ~/.ssh/<ssh_keyfile_nonprod>.pub <ssh_username>@<each-db-host>
```

Host keys are pinned and verified (`RejectPolicy` in `services/ssh_service.py`
and `scripts/parse_slow_queries.py`) — an unrecognized host key is refused
rather than silently trusted, so every host must be added once:

```bash
ssh-keyscan -H <each-db-host> >> ~/.ssh/known_hosts
```

On each MongoDB host, <ssh_username> needs passwordless sudo for exactly the service
commands (nothing else needs root):

```
<ssh_username> ALL=(root) NOPASSWD: /usr/bin/systemctl start mongodb, /usr/bin/systemctl stop mongodb, /usr/bin/systemctl restart mongodb
```

Reading/writing `mongod.conf`, tailing the log, and running `mongodump`
happen as <ssh_username> directly (no sudo) since <ssh_username> already owns
`/apps/DB/modb/`.

## 3. Configure .env — standard location is /etc/mongofleet/.env

`config.py` now looks for `.env` in this order:
1. **`/etc/mongofleet/.env`** — the standard, production location. Both
   the gunicorn/systemd service and any manual `python app.py` /
   `flask db ...` / cron run pick this up automatically, so there is exactly
   one copy of the real secrets on the box instead of two drifting ones.
2. `backend/.env` — dev-only fallback, used only if #1 doesn't exist.

Set it up once:

```bash
sudo mkdir -p /etc/mongofleet
sudo cp /data/database-management/backend/.env.example /etc/mongofleet/.env
sudo vi /etc/mongofleet/.env    # fill PG_PASSWORD, ATLAS_SECRET_KEY, SSH_*, etc.

# <app_service_user> (the service user) must be able to read it; nobody else should:
sudo chown root:<app_service_user> /etc/mongofleet/.env
sudo chmod 640 /etc/mongofleet/.env
```

If <app_service_user> has no sudo on the app server, skip `/etc/mongofleet/.env`
entirely and just place the filled-in file at `backend/.env` (`chmod 600`) —
`config.py` falls back to it automatically when the `/etc` path doesn't exist.

If you still have the old `backend/.env` from an earlier setup, delete it
so there's no ambiguity about which file is authoritative:
```bash
rm -f /data/database-management/backend/.env
```

## 4. Database migrations (Flask-Migrate)

```bash
source venv/bin/activate
export FLASK_APP=app.py
flask db init          # first time only — creates migrations/
flask db migrate -m "initial schema"
flask db upgrade
```

## 5. Seed RBAC and create the first admin user

```bash
python scripts/seed_roles_permissions.py
python scripts/create_admin_user.py     # prompts for password, hidden input
```

## 6. Quick local smoke test

```bash
python app.py     # dev server on 127.0.0.1:8000
curl -s http://127.0.0.1:8000/api/health
```

## 7. Run under gunicorn + systemd

`deploy/mongofleet.service` already points `EnvironmentFile` at
`/etc/mongofleet/.env` (updated to match step 3 above):

```bash
sudo cp deploy/mongofleet.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mongofleet
systemctl status mongofleet --no-pager
```

If SELinux blocks gunicorn from reading `/etc/mongofleet/.env` or
executing the venv binaries, the fix is a context label, not disabling
enforcing mode:
```bash
sudo restorecon -Rv /data/database-management/backend/venv
sudo semanage fcontext -a -t etc_t "/etc/mongofleet(/.*)?"
sudo restorecon -Rv /etc/mongofleet
```

## 8. Point nginx at the API (extends the config you already applied)

Add this **inside** the existing `server { ... }` block in
`/etc/nginx/conf.d/mongofleet.conf`, above the `location /` block:

```nginx
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
```

Then:

```bash
nginx -t
systemctl reload nginx
```

SELinux also needs to allow nginx to make outbound proxy connections to
gunicorn on 127.0.0.1:8000:

```bash
setsebool -P httpd_can_network_connect on
```

## 9. Verify end-to-end

```bash
curl -s http://192.168.45.144/api/health
curl -s -X POST http://192.168.45.144/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<the admin you created>","password":"<its password>"}' -i
```

## ⚠️ Making this reachable from the public internet

You mentioned this needs to be publicly accessible. Worth being clear-eyed
about what that means for *this specific app*, not app hosting in general:
MongoFleet can execute real OS/MongoDB commands (restart, config change,
eventually failover) against your production database estate. Putting its
login page on the open internet over plain HTTP, protected only by one
password, is a meaningfully bigger risk than exposing a normal read-only
website — a brute-forced or phished login is a path straight to production
infrastructure control, not just data disclosure.

If this is genuinely a short-lived POC for a demo, minimum precautions:
- **Put it behind something other than raw port-forwarding if you can** —
  a VPN (WireGuard/OpenVPN) or your router's IP allowlist restricts who can
  even reach port 80, which cuts off the vast majority of internet scanning
  traffic that would otherwise hit this login page within minutes of the
  port opening.
- **`SESSION_COOKIE_SECURE=false` is a temporary HTTP-only accommodation,
  not a target state.** Plan to put nginx behind TLS (even a free Let's
  Encrypt cert once you have a domain name) and flip this back to `true` —
  over plain HTTP, the session cookie and login password both travel in
  clear text and are readable by anything on the network path.
- **Rotate the admin password and secret key** once the POC audience has
  seen it work, per the note at the top of this file — and again after the
  POC ends, before this ever becomes a longer-lived deployment.
- Consider narrowing `firewalld`/router forwarding to specific source IPs
  if only a handful of people need access, rather than 0.0.0.0/0.

None of this blocks you from doing the POC — just flagging it plainly so
it's a deliberate, time-boxed decision rather than something that quietly
becomes permanent.

## New in this drop: live metrics + hourly static-inventory cron

`server-detail.html` now splits its data into two sources that are never
mixed:

- **Live metrics** (CPU%, memory%, disk%, OS uptime, replication lag,
  connections) — pulled fresh over SSH + PyMongo on every page load and on
  "Refresh live metrics", via `GET /api/inventory/servers/:id/live-metrics`.
  Nothing here is stored.
- **Static inventory** (FQDN, OS name, CPU cores, total memory/disk, Mongo
  version/edition) — read straight from the `servers` table, written only by
  `scripts/collect_static_inventory.py` on an hourly schedule.

### Apply the new columns (fqdn, mongo_edition, static_collected_at, static_collection_error)

```bash
su - <app_service_user> -c "
cd /data/database-management/backend
source venv/bin/activate
export FLASK_APP=app.py
flask db migrate -m 'add static inventory columns'
flask db upgrade
"
```

### Schedule the hourly collector (crontab — simplest option)

```bash
chmod +x /data/database-management/backend/scripts/run_static_inventory_collect.sh
su - <app_service_user> -c "crontab -e"
```

Add this line (runs at the top of every hour):

```
0 * * * * /data/database-management/backend/scripts/run_static_inventory_collect.sh
```

Save and check it's registered:

```bash
su - <app_service_user> -c "crontab -l"
```

Logs land in `/data/database-management/logs/static-inventory-cron.log`.

### Run it once by hand to verify before waiting for the cron

```bash
su - <app_service_user> -c "
cd /data/database-management/backend
source venv/bin/activate
python scripts/collect_static_inventory.py
"
```
Expect output like `total=1 ok=1 failed=0 duration=2.3s`. Then reload
`server-detail.html` for that server — the "Last collected …" note under
Infrastructure & OS Specifications should show a real timestamp instead of
"Not yet collected".

### Alternative: systemd timer instead of crontab

If you'd rather not rely on cron, a `systemd` timer works the same way —
happy to provide `mongofleet-static-inventory.service` + `.timer` units if you
want that route instead; crontab is simpler to start with and easy to swap
out later without touching the Python.

## New in this drop: Alerts

Audit logging stays exactly as it was (`audit_service.record()` is still the
only write path into `audit_logs`, still insert-only). Alerts are a
**separate** `alerts` table that references `audit_logs` rows — this avoids
ever adding an UPDATE path to `audit_logs` (which the module's own docstring
says never happens) just to mark "already alerted".

- `services/alert_rules.py` — which audit actions raise an alert, and at what
  severity (CRITICAL/WARNING/INFO). Edit this file to add new rules.
- `services/alert_service.py` — scans audit_logs forward from a saved cursor
  (`alert_poll_state` table, one row), creates `Alert` rows for matches, then
  attempts delivery. A Postgres advisory lock means an overlapping run
  (previous poll still going) just exits immediately instead of double-firing.
- `GET /api/alerts`, `GET /api/alerts/summary`, `POST /api/alerts/poll` —
  backs the new `alerts.html` page (time-range filter, severity/status
  filter, search, Refresh, and a "Check now" button that runs the same cycle
  the cron job runs, for testing before the cron is installed).

### Apply the new tables (alerts, alert_poll_state)

```bash
su - <app_service_user> -c "
cd /data/database-management/backend
source venv/bin/activate
export FLASK_APP=app.py
flask db migrate -m 'add alerts and alert_poll_state tables'
flask db upgrade
"
```

### Schedule the alert poller (every 1 minute)

```bash
chmod +x /data/database-management/backend/scripts/run_poll_alerts.sh
su - <app_service_user> -c "crontab -e"
```

Add this line:

```
* * * * * /data/database-management/backend/scripts/run_poll_alerts.sh
```

Logs land in `/data/database-management/logs/alerts-cron.log`.

### Run it once by hand to verify before waiting for the cron

```bash
su - <app_service_user> -c "
cd /data/database-management/backend
source venv/bin/activate
python scripts/poll_alerts.py
"
```
Expect output like `scanned=6 created=2 sent=2 failed=0 cursor=6 duration=0.1s`.
Then open `alerts.html` — the new alerts should be listed immediately (delivery
channel defaults to `log`, which needs zero setup; see `.env.example` for
adding email via SMTP once that's decided).

### Update: "Agent mesh connected · 12 execution agents online" removed

This decorative pill (top of the sidebar) has now been removed from every
page. It was static markup left over from the original mockup and was never
wired to anything real — there is no agent process in this backend (SSH/PyMongo
calls run synchronously inside the Flask/gunicorn process itself).

## Phase status (mapped to your 25-section spec)

**Implemented and real (no mock data) in this drop:**
- Phase 1–4: project inspected, architecture, Postgres schema (via models.py
  + migrations), Flask foundation, health endpoint, real session-based auth
  and RBAC (permissions/roles/users all backed by Postgres), inventory
  service (CRUD + live SSH/Mongo connectivity test + live health refresh via
  Paramiko/PyMongo, empty until you register real servers).
- Dashboard summary endpoint computed from real DB aggregates.
- SSH execution service: allowlisted command registry only, host-key
  verification via pinned known_hosts, per-credential-ref auth (no single
  shared secret unlocking every host), full audit logging.
- Operation engine (`services/operations_service.py` + `routes/operations.py`):
  real REQUESTED → RUNNING → SUCCESS/FAILED state machine executing
  start/stop/restart/create_user/backup/configure_profiler/configure_auth/
  configure_memory/configure_journal/change_port against real servers over
  SSH/PyMongo, with per-step logs, scheduling, and history — this is the
  piece the previous drop of this README described as "not yet built"; it
  has since been built out on operations.html.
- Monitoring: Performance Advisor (slow query aggregation + index
  recommendations, `routes/monitoring.py`) and a fleet-wide Metrics
  Dashboard (`/api/monitoring/dashboard-stats`, real ServerHealth data) —
  both were fixed/added in this drop. The Performance Advisor blueprint
  existed in code but was never registered on the Flask app and referenced
  two model classes (`SlowQueryLog`, `IndexRecommendation`) that were never
  added to `models.py`, so every button on that tab silently 404'd; both are
  now fixed. A "Launch PMM Dashboard" link was added next to the new stats.
- Audit Logs (`routes/audit.py` + governance.html): previously hardcoded
  mock rows in the page itself; now a real, searchable/filterable endpoint
  over the `audit_logs` table with a working CSV export.
- Alerts: rule-driven, generated from real audit_logs rows on a 1-minute
  poll cycle (cron or manual "Check now"), with a real alerts.html page
  (time-range filter, severity/status filter, search). Delivery channel
  defaults to a zero-setup log channel; email is wired but needs SMTP_*
  configured to actually send.
- The decorative "Agent mesh connected · 12 execution agents online"
  sidebar pill has been removed from every page (see note above).

**Still UI-only / not backed by real execution — be aware before you rely
on these in production:**
- `failover-failback.html`: the topology table (member roles, replication
  lag) and both confirm-and-approve flows ("Initiate failover" /
  "Start controlled failback") are static markup. Clicking through shows a
  toast ("...sent for approval") but nothing is actually submitted to the
  backend — there is no failover/failback operation type in
  `OPERATION_TYPES`, and no approval-workflow table exists yet (the
  `Operation` model does define a `WAITING_FOR_APPROVAL` status for when
  this is built). Do not treat this page as functional; it needs a real
  `failover`/`failback` handler in `operations_service.py` plus an
  approvals table before it can safely trigger anything against a
  production replica set.
- `upgrade.html`: the "Continue to rolling plan" button is intentionally
  `disabled` — the rolling-upgrade plan step past it hasn't been built.

Building the failover/failback and upgrade execution engines with the same
no-mock-data, real-execution standard as the pieces above is a larger,
safety-sensitive effort (it means stepping down a live primary) — happy to
take that on as a dedicated next drop rather than bolting on a fake success
path.
