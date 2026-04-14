# Internal Runtime Hardening

## What Changed

- Unified snapshot cache identity around `school_id + revision + day` inside the project code.
- Stopped deleting token-to-school mapping during revision bumps, so `/api/display/status/` stays cheap and cache-only.
- Normalized day keys to ISO format across snapshot cache, stale fallback, prebuild, and revision bump flows.
- Removed duplicate snapshot body materialization paths that used a fixed TTL and inconsistent keys.
- Added clearer snapshot diagnostics for cache status, payload bytes, build duration, and last revision per school.
- Improved WebSocket observability with reconnect counters, retained reconnect totals, and clearer client/server logs for connect, disconnect, reconnect attempt, and revision invalidate delivery.
- Hardened dashboard login against stale CSRF pages by forcing `never_cache`, ensuring a fresh CSRF cookie, and adding a project-local CSRF failure view with diagnostics.

## Why

- The previous snapshot path used more than one cache key style and more than one day format. That raised avoidable cache misses and repeated rebuilds.
- Deleting token mapping on every revision bump forced extra resolution work right when the system was already under change load.
- Login CSRF failures were hard to diagnose and could be amplified by cached login pages.
- WebSocket health was observable, but reconnect visibility and retained reconnect counts were still incomplete.

## Expected Effect

- Better snapshot cache reuse for the same revision/day.
- Fewer repeated snapshot builds during steady-state polling.
- Lower load on `/api/display/status/` after revision bumps.
- Faster diagnosis of CSRF and WebSocket issues from project logs and built-in metrics endpoints.

## Remaining Outside Project Scope

- CDN/proxy cache rules for login pages and API paths were not changed here.
- Render/Cloudflare/WebSocket proxy idle timeout tuning was not changed here.
- External headers such as forwarded host/origin behavior still depend on deployment configuration.

## TODO Outside Project

- Verify reverse proxy passes correct `Origin`, `Host`, and `X-Forwarded-Proto` consistently on dashboard login.
- Ensure any external cache layer bypasses or disables caching for `/dashboard/login/`.
- Review proxy/WebSocket idle timeout and keepalive settings if disconnects still cluster around a fixed interval.