# SaaS Remediation Report

Date: 2026-04-01

## Scope

This remediation focused on the highest-risk runtime issue discovered during the SaaS review:

- broken `snapshot` execution flow in `schedule/api_views.py`
- failing display contract tests
- unstable response semantics around device binding, cache headers, and ETag handling
- missing image optimization before upload for logos, excellence photos, and subscription receipts
- avoidable snapshot CPU work on cache hits and low steady-cache efficiency outside active windows

## Fixes Applied

### 1. Restored the missing `snapshot` request flow

The current local `snapshot()` implementation had an invalid early build path that executed before:

- token extraction
- device binding validation
- cache-key initialization
- school/revision resolution

This caused the server to call `get_or_build_snapshot(school_id, rev, ...)` while both values were still `None`.

Applied fix:

- restored token extraction before any build attempt
- restored path-level device-key enforcement for `/api/display/snapshot/*`
- restored device binding guard and `screen_bound` rejection path
- restored token-cache fast path and school shared-cache fast path
- restored anti-loop and snapshot rate-limit logic
- kept the later, correct build path as the only place where snapshot bodies are built

### 2. Normalized response finalization

`snapshot` responses now consistently finalize with:

- `Cache-Control`
- `Vary: Accept-Encoding`
- cache diagnostic headers
- device-bound headers
- revision/school metadata headers
- app revision header when available

This brings successful and error responses back in line with the display API contract.

### 3. Recovered test-visible behavior

The following behaviors are now working again:

- `403` when snapshot device key is missing
- `403` when a second device tries to use a bound screen
- `429` on snapshot burst rate limiting
- stable `ETag` generation and `304` revalidation
- correct school isolation between tenant snapshots
- safe no-schedule payload shape and cacheability

### 4. Added server-side upload optimization for image inputs

The platform did not previously compress or normalize uploaded images before persisting them.

Applied fix:

- added centralized image optimization in `core/image_uploads.py`
- re-encode large uploads to `webp` when that reduces storage cost
- resize oversized uploads before persistence to bounded dimensions
- keep the original file when re-encoding is not beneficial and no resize is needed
- applied optimization to:
  - school logos in dashboard school forms and school settings forms
  - excellence photos in both dashboard and notices forms
  - subscription receipt images before request persistence

Operational effect:

- lower media storage footprint
- lower upload and fetch bandwidth for newly uploaded images
- reduced pressure on disk/cloud media storage and admin upload flows

### 5. Reduced snapshot CPU cost and improved cache effectiveness

The snapshot path was still doing unnecessary work on cache hits:

- repeated JSON serialization on school-level cache hits
- repeated `ETag` hashing on already-built payloads
- steady snapshot keys were revision-based but not day-aware, which forced conservative TTL choices

Applied fix:

- changed steady snapshot cache keys to include both `revision` and snapshot `date`
- bumped the steady cache namespace version to invalidate older non-day-aware keys safely
- stored snapshot cache entries as an envelope containing:
  - `snap`
  - precomputed `body`
  - precomputed `etag`
- served cached snapshot hits directly from the cached JSON body instead of rebuilding JSON every time
- raised the default steady snapshot TTL ceiling from 10 minutes to 60 minutes for non-active states, now that the key is day-aware

Operational effect:

- lower CPU cost per snapshot cache hit
- fewer unnecessary steady-state rebuilds
- better cache safety across day boundaries
- more headroom for fleets with many display clients polling the same school snapshots

## Verification

### Targeted display tests

Command:

```powershell
.\.venv\Scripts\python.exe manage.py test schedule.tests.DisplayApiAliasesTests schedule.tests.DisplaySnapshotPhase2Tests dashboard.tests_display.DashboardDisplayContractTests -v 2
```

Result:

- 20 tests
- 20 passed

### Targeted upload optimization tests

Command:

```powershell
.\.venv\Scripts\python.exe manage.py test dashboard.tests_uploads -v 2
```

Result:

- 3 tests
- 3 passed

### Targeted snapshot cache tests

Command:

```powershell
.\.venv\Scripts\python.exe manage.py test schedule.tests.DisplayApiAliasesTests schedule.tests.DisplaySnapshotPhase2Tests schedule.tests.SnapshotTtlHelpersTests -v 2
```

Result:

- 19 tests
- 19 passed

### Full local test suite

Command:

```powershell
.\.venv\Scripts\python.exe manage.py test -v 1
```

Result:

- 49 tests
- 49 passed

### Syntax validation

Command:

```powershell
python -m py_compile schedule/api_views.py
```

Result:

- passed

## Files Changed

- `schedule/api_views.py`
- `core/image_uploads.py`
- `dashboard/forms.py`
- `notices/forms.py`
- `dashboard/tests_uploads.py`
- `schedule/tests.py`
- `docs/saas-remediation-report-2026-04-01.md`

## Operational Impact

This remediation addresses the most urgent production-alignment problem:

- snapshot generation no longer depends on uninitialized `school_id` and `rev`
- display clients again enforce single-device binding correctly
- snapshot responses are again cacheable and revalidatable as intended
- uploaded images now consume fewer storage and transfer resources by default
- snapshot cache hits now avoid repeated JSON/ETag work and are safer across day transitions

## Remaining SaaS Priorities

These items were identified during the earlier audit and are still recommended next:

1. Harden production defaults in `config/settings.py`
   - remove development-default `DEBUG=True`
   - tighten authentication defaults where possible

2. Improve WebSocket resilience
   - investigate repeated `1006` disconnects from production logs
   - review heartbeat/proxy timeout strategy

3. Improve snapshot cache efficiency
   - production logs still show weak steady/token cache hit ratios
   - review key strategy, TTL balance, and duplicate cache layers

4. Strengthen SaaS platform controls
   - stronger tenant enforcement
   - finer-grained RBAC
   - enforce all subscription entitlements, not just screen limits

5. Improve observability and operations
   - central error tracking
   - durable metrics across workers
   - CI/CD and deployment consistency checks

## Notes

- `config/settings.py` already had local modifications in the working tree before this remediation; this pass did not alter that file.
- The main objective of this pass was to remove the critical display regression and restore test-backed correctness first.
