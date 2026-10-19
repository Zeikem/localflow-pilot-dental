# DentalFlow read-only bridge (pilot)

This is a **read-only**, minimum-data interface connecting the existing FastAPI LocalFlow Core to the Windows Django DentalFlow interface. It is separate from the Meta webhook and does not change WhatsApp flow.

## API

A new router is registered in `app/main.py`:

- `GET /admin/bridge/events?tenant_slug=dental-pilot-leon&limit=100`
- `GET /admin/bridge/appointments?tenant_slug=dental-pilot-leon&limit=200`

Both require `X-LocalFlow-Bridge-Token` and a **different** random 32+ character secret named `LOCALFLOW_BRIDGE_READ_TOKEN` in the API environment.

**Do not reuse `ADMIN_API_TOKEN`, Meta tokens, or WhatsApp access tokens.** The endpoints return HTTP 503 until the new secret is configured and the service restarted.

Events contain only an SHA-256 digest of the Meta event ID, administrative status, source channel and timestamp; appointment records contain only an opaque UUID, date, service and resource code and status. Neither endpoint includes names, phone numbers, original WhatsApp bodies, answers, medical records or financial details.

Each query checks an explicitly named **active** tenant and does not enumerate all tenants. Event pagination is cursor based; two consecutive syncs use deduplication.

## Activation process

1. Review this PR and the 61 passing unit tests; merge only after explicit approval.
2. Railway's current `api-image` service runs `ghcr.io/zeikem/localflow-pilot-dental:railway`, **not** a live GitHub checkout. Merging this PR **will not deploy the changes**. Build and deploy an updated image or connect a suitable repository source, after checking the deployment setup.
3. Generate a strong, distinct bridge secret and configure the same value under:
   - Railway `api-image`: `LOCALFLOW_BRIDGE_READ_TOKEN`
   - Windows Django private `.env`: `LOCALFLOW_CORE_BRIDGE_READ_TOKEN`
4. In Windows Django's `.env`, also set:
   - `LOCALFLOW_CORE_BRIDGE_URL=https://api-image-production-7f8d.up.railway.app`
   - `LOCALFLOW_CORE_TENANT_SLUG=dental-pilot-leon`
5. On the PC, execute `python manage.py sync_localflow_core` without flags first. This downloads and validates only aggregate metadata and **does not write**.
6. Only after inspecting the dry-run report run `python manage.py sync_localflow_core --apply`. The local UI displays the synced signals in Bandeja and the appointments under Agenda → Citas de Railway.

The Django integration deliberately keeps appointments in **a separate read-only mirror**. The local and cloud agendas do not share booking locks. Do not claim cross-calendar collision protection or real-time synchronization.

## Scope, limits, security

- This feature makes no contact with patients and cannot send outbound messages.
- A compromised bridge token may read *administrative* metadata for an explicitly requested tenant. Rotate it if leaked. Do not place secrets in the Git repository.
- The API currently allows querying any active tenant by slug when a valid bridge token is supplied, so **never share this service's token with client clinics** or use it for a multi-tenant self-service SaaS. A future production release needs a server-side token-to-tenant binding.
- Django validation additionally requires the exact preapproved Railway hostname and tenant slug in local config.
- Local syncing limits work to 2,000 events per run (20 pages of 100), and displays the newest 200 appointments. This is a pilot limit, not an archival export.
- Do not migrate to a clinic with real patient data until contracts, authorization, privacy and restore procedures are reviewed.

## Tests
```
python -m unittest discover -s tests -v
```

Current staged results: 61/61 unit tests passed on the Windows test copy. Production Railway endpoints are **not deployed or verified**.
