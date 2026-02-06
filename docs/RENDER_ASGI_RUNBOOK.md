# Render ASGI Deployment Runbook

**Target:** Migrate from WSGI (Gunicorn) to ASGI (Daphne) on Render  
**Downtime:** Zero (rolling deploy)  
**Rollback Time:** < 5 minutes  
**Date:** 2026-02-06

---

## Pre-Migration Checklist

- [ ] **Redis service is running** on Render (required for channel layer)
  - Verify: `REDIS_URL` env var is set and accessible
  - Test: Run `redis-cli -u $REDIS_URL ping` → should return `PONG`

- [ ] **Feature flag is OFF initially**
  - Set `DISPLAY_WS_ENABLED=false` in Render env vars
  - This ensures WS infrastructure exists but is inactive

- [ ] **Backup current `render.yaml`**
  ```yaml
  # Current (WSGI)
  startCommand: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 4
  ```

- [ ] **Dependencies merged to main branch**
  - `channels==4.0.0`, `channels-redis==4.2.0`, `daphne==4.1.0` in `requirements.txt`
  - All code changes from Phase 0-2 merged

- [ ] **Local testing passed**
  - Run `daphne -b 127.0.0.1 -p 8000 config.asgi:application` locally
  - Verify HTTP requests work (`/api/display/snapshot/`, admin, static files)
  - Verify WS connection closes with `4400` (feature disabled)

---

## Step 1: Update Render Configuration

### A) Update `render.yaml`
```yaml
services:
  - type: web
    name: school-display
    env: python
    region: frankfurt  # or your region
    
    buildCommand: |
      pip install --upgrade pip
      pip install -r requirements.txt
      python manage.py collectstatic --noinput --clear
    
    # ✅ CHANGE: Use Daphne instead of Gunicorn
    startCommand: daphne -b 0.0.0.0 -p $PORT config.asgi:application
    
    envVars:
      - key: PYTHON_VERSION
        value: 3.11.0
      - key: DISPLAY_WS_ENABLED
        value: false  # ✅ Keep disabled initially
      # ... other env vars
```

**Why Daphne?**
- Fully async ASGI server (supports WebSocket + HTTP)
- Battle-tested (used by Django Channels docs)
- Graceful handling of long-lived connections

**Alternative (if Daphne issues):**
```yaml
startCommand: uvicorn config.asgi:application --host 0.0.0.0 --port $PORT --workers 4
```
(Uvicorn is also ASGI-compliant; choose based on performance testing)

---

### B) Environment Variables
Add/verify in Render dashboard:
```bash
DISPLAY_WS_ENABLED=false          # Feature flag (OFF initially)
REDIS_URL=<your-redis-url>        # Must be set
CHANNEL_LAYERS_BACKEND=channels_redis.core.RedisChannelLayer
```

---

## Step 2: Deploy to Render

### A) Trigger Deploy
1. Commit `render.yaml` changes to main branch
2. Render auto-deploys (or trigger manually)
3. Monitor build logs:
   ```
   Building...
   Installing channels, channels-redis, daphne...
   Collecting static files...
   ```

### B) Health Check During Deploy
**Critical:** Render performs rolling deploy → old instances stay up until new ones are healthy.

Watch logs for:
```
[INFO] daphne.server: Listening on TCP address 0.0.0.0:10000
```

**Test immediately after deploy:**
```bash
# 1. HTTP still works
curl https://your-app.onrender.com/api/display/snapshot/test-token/

# 2. Static files load
curl -I https://your-app.onrender.com/static/css/display.css

# 3. Admin accessible
curl -I https://your-app.onrender.com/admin/
```

**Expected result:** All return 200/30x as before (no 500 errors).

---

### C) Verify ASGI Behavior
```bash
# WebSocket connection attempt (should close with 4400 since feature disabled)
wscat -c "wss://your-app.onrender.com/ws/display/?token=test&dk=test123"

# Expected output:
# < Disconnected (code: 4400)
```

**Why this is good:**
- WS routing works (consumer accepted connection)
- Feature flag works (consumer closed after checking `DISPLAY_WS_ENABLED=false`)
- HTTP unaffected

---

## Step 3: Production Smoke Test

### A) Critical Paths (should behave identically to before)
1. **Snapshot endpoint:**
   ```bash
   curl -H "If-None-Match: \"abc123\"" \
        https://your-app.onrender.com/api/display/snapshot/<real-token>/ \
        -w "\nHTTP %{http_code} | ETag: %{header_etag}\n"
   ```
   Expected: `304 Not Modified` or `200 OK` with valid JSON

2. **Status endpoint:**
   ```bash
   curl "https://your-app.onrender.com/api/display/status/<real-token>/?v=100"
   ```
   Expected: `{"fetch_required": true/false, ...}` or `304`

3. **Device binding (403 on mismatch):**
   ```bash
   curl "https://your-app.onrender.com/api/display/snapshot/<bound-token>/?dk=wrong-device"
   ```
   Expected: `403 {"detail": "screen_bound", ...}`

4. **Static files (WhiteNoise):**
   ```bash
   curl -I https://your-app.onrender.com/static/js/display.js
   ```
   Expected: `200 OK` with `Cache-Control` header

---

### B) Monitor Metrics (First 30 Minutes)
- **Error rate:** Should remain < 0.1% (same as baseline)
- **Response time (p95):** Should remain < 300ms for snapshot
- **Memory usage:** May increase ~50MB (Daphne + channel layer overhead)
- **CPU usage:** Should remain stable (WS not enabled yet)

**Tools:**
- Render Metrics dashboard
- Application logs: `grep ERROR`
- Sentry/error tracking (if configured)

---

### C) Rollback Decision Point
**If any of these occur:**
- HTTP response errors > 1% of requests
- Static files fail to load (404/500)
- Snapshot ETag/304 logic breaks (always 200)
- Memory/CPU spike > 2× baseline

**→ Execute Rollback (see Step 6)**

---

## Step 4: Enable WebSocket (Gradual)

### A) Test School (1 screen)
1. In Render env vars, set:
   ```
   DISPLAY_WS_ENABLED=true
   ```
2. Redeploy (or restart service if hot-reload enabled)
3. Open test school display screen
4. Check browser console:
   ```
   [WS] connecting to wss://...
   [WS] connected
   ```
5. Edit test school schedule → verify:
   - WS message received: `[WS] invalidate received: revision 123`
   - Screen refreshes < 1s
6. **Disconnect WiFi** → verify:
   - WS closes → reconnects with backoff
   - Polling continues normally (screen still updates every 8-45s)

**Success criteria:**
- No `screen_bound` errors
- WS connection stable (stays open > 10 minutes)
- Polling fallback works when WS disconnected

---

### B) Expand Rollout
Follow **Phase 3 plan** (5 schools → 20 → 25% → 50% → 100%)

At each stage:
- Monitor for 24-48h
- Check WS connection count (Render logs: `grep "WS connected"`)
- Verify polling fallback ratio < 20%

**Abort if:**
- WS disconnects > 30% of connections within 5 minutes
- `screen_bound` errors spike > 5%
- Snapshot latency increases > 2× baseline

**To abort:** Set `DISPLAY_WS_ENABLED=false` → instant disable (no deploy needed, next snapshot fetch will turn off WS for all clients)

---

## Step 5: Post-Production Monitoring

### A) Key Metrics (Ongoing)
```bash
# 1. WS connection count (should match enabled screens)
grep "WS connected" logs | wc -l

# 2. Broadcast success rate (should be ~100%)
grep "WS broadcast sent" logs | wc -l

# 3. Polling fallback usage (should be < 5% when WS healthy)
grep "status 304" logs | wc -l

# 4. Device binding rejections (should remain < 1%)
grep "device_binding_reject" logs | wc -l
```

### B) Alerts (Recommended)
- **Error:** `screen_bound` rate > 5% of requests
- **Warning:** WS reconnect rate > 10 reconnects/min
- **Info:** Memory usage > 1.5× baseline (investigate channel layer leak)

---

## Step 6: Rollback Procedure

### Scenario 1: ASGI Broken (HTTP fails)
**Symptoms:** 500 errors, static files 404, admin unreachable

**Fix (< 5 minutes):**
1. Revert `render.yaml`:
   ```yaml
   startCommand: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 4
   ```
2. Commit + push to main
3. Render auto-deploys (or trigger manual deploy)
4. Verify HTTP works: `curl https://your-app.onrender.com/admin/`

**Result:** System reverts to WSGI (pre-migration state), polling-only.

---

### Scenario 2: WebSocket Causing Issues (HTTP works, but WS unstable)
**Symptoms:** WS reconnect storms, `screen_bound` errors spike, memory leak

**Fix (< 1 minute, no deploy needed):**
1. In Render env vars, set:
   ```
   DISPLAY_WS_ENABLED=false
   ```
2. Restart service (or wait for next snapshot fetch across all screens)
3. Clients will read `meta.ws_enabled=false` → close WS → rely on polling

**Result:** ASGI remains (HTTP unchanged), WS disabled globally → polling-only behavior.

---

### Scenario 3: Specific School Issues (WS works for most, fails for one)
**Symptoms:** One school's screens get `4408` errors repeatedly

**Fix (< 2 minutes, no deploy needed):**
1. **Temporary:** Unbind affected screens in dashboard:
   ```python
   # Django shell
   from core.models import DisplayScreen
   DisplayScreen.objects.filter(school_id=<problem-school>).update(bound_device_id=None)
   ```
2. Screens will rebind on next fetch (atomic logic prevents race)
3. **Root cause:** Investigate device ID collisions (e.g., multiple tabs with same localStorage)

**Result:** Affected screens recover, rest of system unaffected.

---

## Step 7: Verification After Rollback

**After Scenario 1 (full rollback to WSGI):**
- [ ] HTTP snapshot returns 200/304 as expected
- [ ] Static files load
- [ ] Device binding rejects mismatches (403)
- [ ] Polling intervals match pre-migration (8-45s adaptive)

**After Scenario 2 (WS disabled, ASGI kept):**
- [ ] All above ✅
- [ ] No WS connections in logs (`grep "WS connected"` returns 0)
- [ ] Clients show polling-only behavior (no WS attempts in browser console)

---

## Troubleshooting Guide

### Issue: Static Files 404 After ASGI Deploy
**Cause:** WhiteNoise middleware ordering or `collectstatic` not run

**Fix:**
```bash
# Rebuild with fresh collectstatic
python manage.py collectstatic --noinput --clear
```
Verify `MIDDLEWARE` order in `settings.py`:
```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # Must be after SecurityMiddleware
    ...
]
```

---

### Issue: WS Connections Timeout After 60s
**Cause:** Render proxy timeout (default 60s for idle connections)

**Fix:** Enable keepalive ping (already implemented in `display.js`):
```javascript
// Client sends ping every 30s
rt.wsPingInterval = setInterval(() => {
  rt.ws.send(JSON.stringify({ type: "ping" }));
}, 30000);
```

If still fails, add to `settings.py`:
```python
CHANNEL_LAYERS = {
    "default": {
        "CONFIG": {
            "hosts": [REDIS_URL],
            "capacity": 1000,
            "expiry": 60,  # Increase if needed
        },
    },
}
```

---

### Issue: Memory Usage Increases Over Time
**Cause:** Channel layer message accumulation or WS connection leaks

**Debug:**
```bash
# Check Redis memory usage
redis-cli -u $REDIS_URL INFO memory

# Check active WS connections
grep "WS connected" logs | tail -100
grep "WS disconnected" logs | tail -100
```

**Fix:**
- Ensure `rt.ws.close()` called on client navigate-away
- Reduce channel layer `expiry` (currently 60s)
- Monitor for orphaned groups (shouldn't happen with proper disconnect handling)

---

### Issue: Broadcast Not Reaching Clients
**Symptoms:** Edits don't trigger WS invalidate, screens only update via polling

**Debug:**
```bash
# Check if broadcasts are sent
grep "WS broadcast sent" logs

# Check if clients are in correct group
# (should see group name in WS connect logs)
grep "WS connected.*school:" logs
```

**Fix:**
- Verify `DISPLAY_WS_ENABLED=true` in env vars
- Check signals are firing: `grep "schedule_revision bumped" logs`
- Ensure Redis channel layer is configured correctly (not fallback to InMemory)

---

## Success Criteria (Final)

✅ **HTTP endpoints:** Response times unchanged (< 300ms p95)  
✅ **Static files:** Load correctly via WhiteNoise  
✅ **Device binding:** Atomic, no race conditions  
✅ **WebSocket:** Stable connections (< 2% disconnect rate)  
✅ **Broadcast latency:** < 1s from edit to screen update  
✅ **Polling fallback:** Works seamlessly when WS disconnected  
✅ **Memory:** Stable (< 1.5× baseline over 7 days)  
✅ **Error rate:** < 0.1% (same as WSGI baseline)  

---

## Command Reference

**Testing locally:**
```bash
# ASGI server
daphne -b 0.0.0.0 -p 8000 config.asgi:application

# WebSocket test
wscat -c "ws://localhost:8000/ws/display/?token=xxx&dk=yyy"

# HTTP test
curl http://localhost:8000/api/display/snapshot/xxx/
```

**Production (Render):**
```bash
# Tail logs
render logs --tail

# Restart service
render services restart <service-id>

# Check env vars
render env ls
```

---

## Contact & Escalation

**Primary:** Deployment team  
**Secondary:** DevOps (Redis issues)  
**Escalation:** CTO (if rollback doesn't resolve within 30 min)

---

**Appendix A: Render YAML (Final)**
```yaml
services:
  - type: web
    name: school-display
    env: python
    region: frankfurt
    plan: standard
    
    buildCommand: |
      pip install --upgrade pip
      pip install -r requirements.txt
      python manage.py collectstatic --noinput --clear
    
    startCommand: daphne -b 0.0.0.0 -p $PORT config.asgi:application
    
    healthCheckPath: /health/  # Optional: add health endpoint
    
    envVars:
      - key: PYTHON_VERSION
        value: 3.11.0
      - key: DJANGO_SETTINGS_MODULE
        value: config.settings
      - key: DISPLAY_WS_ENABLED
        value: false  # Toggle to true for Phase 3
      - key: REDIS_URL
        fromService:
          name: school-display-redis
          type: redis
          property: connectionString
      # ... other env vars
  
  - type: redis
    name: school-display-redis
    region: frankfurt
    plan: starter  # Upgrade if > 1000 concurrent WS connections
    maxmemoryPolicy: allkeys-lru
```
