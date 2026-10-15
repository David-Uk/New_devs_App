# Dashboard Page — Findings & Suggested Fixes

Scope: issues affecting the **`/dashboard`** page only (revenue data path). Read-only analysis; no code was changed.

## Affected endpoint / request chain

```
Dashboard.tsx → RevenueSummary.tsx
  → GET /api/v1/dashboard/summary?property_id=…&_t=…   (X-Simulated-Tenant header)
    → backend/app/api/v1/dashboard.py
      → backend/app/services/cache.py       (Redis, 300s TTL)
        → backend/app/services/reservations.py (DB pool → mock fallback)
          → backend/app/core/database_pool.py
```

Only one real backend endpoint serves this page: **`GET /api/v1/dashboard/summary`** (`backend/app/api/v1/dashboard.py:8`).

---

## 1. Errors / bugs

### 1.1 Cross-tenant cache leak (Client B privacy issue)
- **Where:** `backend/app/services/cache.py:13` — `cache_key = f"revenue:{property_id}"`.
- **Problem:** Cache key omits `tenant_id`. Seed data gives **both tenants the same property id** `prop-001` (`database/seed.sql:6-7`: Sunset "Beach House Alpha" / Ocean "Mountain Lodge Beta"). First requester caches under `revenue:prop-001`; the other tenant receives the first tenant's numbers for up to 300 seconds. The cached payload also contains the other tenant's `tenant_id`.
- **Impact:** "Sometimes when we refresh, we see revenue that belongs to another company."

### 1.2 Database pool can never initialize → hardcoded mock data (Client A totals wrong)
- **Where:**
  - `backend/app/core/database_pool.py:18` builds the URL from `settings.supabase_db_user/password/host/port/name` — **these settings do not exist** in `backend/app/config.py` (only `database_url`, which no code ever reads; docker-compose's `DATABASE_URL` is unused).
  - `backend/app/services/reservations.py:43-46` — pool `session_factory` stays `None`, so `calculate_total_revenue` raises and falls into a **bare `except`** (`reservations.py:88`).
- **Problem:** The real DB is never queried; **every request returns fabricated data with HTTP 200**.
- **Impact:** Silent wrong totals; no error surfaces anywhere.

### 1.3 Mock data is tenant-blind
- **Where:** `backend/app/services/reservations.py:93-101` — mock keyed only by `property_id`.
- **Problem:**
  - `prop-001` mock = `1000.00 / 3` bookings, but reality is **tenant-a: 2250.000 / 4** (1250 + 333.333×2 + 333.334) and **tenant-b: 0.00 / 0** (no reservations).
  - Client B sees numbers that never existed for them; Client A's `prop-001` is wrong by 1250.00.
  - Mocks for `prop-002…005` exactly equal the seeded sums — masking the broken DB path.

### 1.4 Money converted to float (cents drift)
- **Where:** `backend/app/api/v1/dashboard.py:18` — `float(revenue_data['total'])`; then `frontend/src/components/RevenueSummary.tsx:64` — `Math.round(data.total_revenue * 100) / 100`.
- **Problem:** Exact `Decimal` money becomes IEEE-754 float and is rounded again in JS. The schema stores `NUMERIC(10,3)` sub-cent values (`database/schema.sql:28`, e.g. `333.333`); per-item rounding of the three `res-dec` rows = `999.99` vs exact `1000.00` (verified). This is the "off by a few cents" finance issue.

### 1.5 No tenant-ownership check + silent tenant fallback
- **Where:** `backend/app/api/v1/dashboard.py:8-16`.
- **Problem:**
  - `property_id` is accepted from the query with **no validation that it belongs to the caller's tenant**.
  - `getattr(current_user, "tenant_id", "default_tenant") or "default_tenant"` silently collapses any tenant-resolution failure into one shared `"default_tenant"` namespace.

### 1.6 Monthly vs all-time mismatch (Client A "March" issue)
- **Where:** page copy `frontend/src/components/Dashboard.tsx:26` ("Monthly performance insights") vs `dashboard.py` — **no date filter at all**; the endpoint sums every reservation ever (or serves mock).
- **Related dead code:** `backend/app/services/reservations.py:5-32` `calculate_monthly_revenue`:
  - returns a placeholder `Decimal('0')` and is never called;
  - SQL binds `tenant_id = $2` but the signature has **no `tenant_id` parameter**;
  - month boundaries are naive server/UTC datetimes (`reservations.py:10-14`), ignoring `properties.timezone`. Seed `res-tz-1` = `2024-02-29 23:30 UTC` = **March 1 in Paris** → wrong-month bucketing for Paris properties.

### 1.7 Per-request pool construction
- **Where:** `backend/app/services/reservations.py:43-44` creates a new `DatabasePool()` every call instead of using the global `db_pool` (`database_pool.py:55`); never closed.

---

## 2. Mismatches (display vs data)

| Display | Reality |
|---|---|
| "Monthly performance insights" (`Dashboard.tsx:26`) | Endpoint has no date filtering; returns all-time totals |
| `prop-001` labeled "Beach House Alpha" (`Dashboard.tsx:5`) | For Ocean Rentals `prop-001` is "Mountain Lodge Beta" (`seed.sql:6-7`) |
| `prop-001` total `1000.00 / 3` (mock) | tenant-a real: `2250.000 / 4`; tenant-b real: `0.00 / 0` |
| `X-Simulated-Tenant` header sent (`RevenueSummary.tsx:31`, `secureApi.ts:1464`) | **No backend code reads this header** (and value `'candidate'` is not a tenant id) |
| `_t=Date.now()` cache buster (`secureApi.ts:1457-1459`) | `dashboard.py` ignores it; Redis still serves 300s-old data |

---

## 3. Hardcoded data

- `Dashboard.tsx:4-10` — property picker hardcodes **all 5 properties from both tenants** (never fetched per-tenant).
- `Dashboard.tsx:13` / `RevenueSummary.tsx:17` — default `prop-001` (the colliding ID).
- `reservations.py:93-99` — hardcoded mock revenue dict.
- `reservations.py:73,82,107` — `currency: "USD"` hardcoded; ignores `reservations.currency` column.
- `RevenueSummary.tsx:84-89` — fake "12%" trend badge, rendered unconditionally.
- `RevenueSummary.tsx:22` — hardcoded tenant `'candidate'`.
- `dashboard.py:14` — fallback literal `'default_tenant'`.

---

## 4. Things that simplify / mask the problem

1. **Mock data keeps the UI looking healthy** — `prop-002…005` mocks match seeded sums exactly; only `prop-001` diverges, hiding the dead DB path.
2. **Bare `except`** (`reservations.py:88`) swallows the pool failure — fabricated 200 responses instead of errors.
3. **Precision-mismatch warning is unreachable** — gated behind `showRaw` (`RevenueSummary.tsx:107`), which `Dashboard.tsx:49` never passes.
4. **Dead `calculate_monthly_revenue`** returning `Decimal('0')` keeps the timezone bug off the live path.
5. **`or "default_tenant"`** hides tenant-resolution failures.
6. **No cache invalidation** — stale/cross-tenant results persist for 300s with no bust mechanism (the frontend `_t` param is cosmetic).

---

## 5. Suggested fixes (not applied)

### `GET /api/v1/dashboard/summary` — `backend/app/api/v1/dashboard.py`
1. Validate `property_id` belongs to `current_user.tenant_id` (lookup `(id, tenant_id)` in `properties`); return 403/404 otherwise.
2. Remove `or "default_tenant"` — fail loudly when `tenant_id` cannot be resolved.
3. Keep money exact: drop `float(...)`; return the string/`Decimal` (optionally `quantize(Decimal('0.01'))`) so floats never enter JSON.
4. If the page stays "monthly": accept optional `month`/`year` params and compute month boundaries in the **property's timezone** (`properties.timezone`, `zoneinfo`), not naive UTC datetimes.

### Cache — `backend/app/services/cache.py`
5. Scope the key: `revenue:{tenant_id}:{property_id}` (line 13). **This alone fixes the cross-tenant leak.**
6. Add cache invalidation (or expose an endpoint); remove or actually implement the frontend `_t` cache-buster.

### Revenue service — `backend/app/services/reservations.py` + `database_pool.py`
7. Fix pool URL: use `settings.database_url` (convert to `postgresql+asyncpg://`) instead of the nonexistent `settings.supabase_db_*` fields (`database_pool.py:18`).
8. Remove the mock dict and bare `except` (`reservations.py:88-109`) — surface DB errors instead of returning fabricated data.
9. Reuse the global `db_pool` (`database_pool.py:55`) instead of constructing a pool per request.
10. `calculate_monthly_revenue`: add the missing `tenant_id` parameter, use timezone-aware boundaries, and wire it up or delete it (currently dead code returning `Decimal('0')`).
11. Return `reservations.currency` instead of hardcoded `"USD"`.

### Frontend — `Dashboard.tsx` / `RevenueSummary.tsx`
12. Fetch the property list per tenant from the API instead of the hardcoded `PROPERTIES` array (fixes wrong names + exposing the other tenant's properties).
13. Remove debug artifacts: `X-Simulated-Tenant: 'candidate'` header, fake "12%" badge.
14. Align copy with data: change "Monthly performance insights" or implement month filtering (see #4).
15. Money display: derive cents from the exact value string instead of `Math.round(float * 100) / 100`; pass `showRaw` (or remove the gate at `RevenueSummary.tsx:107`) so the precision warning can appear.

### Priority
1. **#5** (cache key) — stops the privacy incident.
2. **#7–8** (pool + mock removal) — restores correct totals.
3. **#1–3** (tenant validation + Decimal) — closes spoofing and cents drift.
4. **#12–15** (frontend) — removes hardcoded/masked data.
