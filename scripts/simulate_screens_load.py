import time
import random
import os
import json
import heapq
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from urllib.error import HTTPError
import urllib.request

# Configuration (can be overridden via env)
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
TOKEN = os.getenv("TOKEN", "")  # must be a valid display token
NUM_SCREENS = int(os.getenv("NUM_SCREENS", "1000"))
DURATION_SEC = int(os.getenv("DURATION_SEC", "60"))

# To simulate ~67-200 RPS with 1000 screens, use 5-15s or 10-20s.
POLL_MIN = float(os.getenv("POLL_MIN", "5"))
POLL_MAX = float(os.getenv("POLL_MAX", "15"))

# Bounded concurrency (avoid 1000 OS threads)
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "200"))
MAX_INFLIGHT = int(os.getenv("MAX_INFLIGHT", "400"))

# Optional: protect metrics endpoint in prod
METRICS_KEY = os.getenv("DISPLAY_METRICS_KEY", "").strip()

def _http_get(url: str, timeout: float = 8.0, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return e.code, body


def _metrics_snapshot():
    url = f"{BASE_URL}/api/display/metrics/"
    headers = {"Accept": "application/json"}
    if METRICS_KEY:
        headers["X-Display-Metrics-Key"] = METRICS_KEY
    code, body = _http_get(url, timeout=3.0, headers=headers)
    if code != 200:
        return None
    try:
        return json.loads(body.decode("utf-8") or "{}")
    except Exception:
        return None


def _one_poll(screen_id: int, local_version: int):
    device_id = f"loadtest-dev-{screen_id}"
    start_req = time.perf_counter()
    status_url = f"{BASE_URL}/api/display/status/?token={TOKEN}&v={local_version}&dk={device_id}"
    code, body = _http_get(status_url, timeout=5.0)
    latency_ms = (time.perf_counter() - start_req) * 1000.0

    if code == 200:
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            data = {}
        server_ver = data.get("schedule_revision", data.get("current_version", 0))
        fetch_required = bool(data.get("fetch_required"))
        snap_code = None
        if fetch_required:
            snap_url = f"{BASE_URL}/api/display/snapshot/?token={TOKEN}&dk={device_id}"
            snap_code, _ = _http_get(snap_url, timeout=8.0)
        return code, latency_ms, int(server_ver or 0), fetch_required, snap_code

    # 304 / errors
    return code, latency_ms, local_version, False, None

def run_load_test():
    if not TOKEN:
        print("ERROR: TOKEN env var is required (must be a valid display token).")
        return

    print(f"--- Starting Load Test: {NUM_SCREENS} screens for {DURATION_SEC}s ---")
    print(f"Base URL: {BASE_URL}")
    print(f"Poll interval range: ({POLL_MIN}, {POLL_MAX})s")
    print(f"Concurrency: workers={MAX_WORKERS} inflight={MAX_INFLIGHT}")

    start_metrics = _metrics_snapshot()
    if start_metrics is None:
        print("WARN: /api/display/metrics/ not available (DEBUG only unless enabled).")

    stats = {
        "requests": 0,
        "304": 0,
        "200_update": 0,
        "snapshots": 0,
        "errors": 0,
        "latencies": [],
    }

    local_versions = [0] * NUM_SCREENS

    start_t = time.perf_counter()
    end_t = start_t + float(DURATION_SEC)

    heap = []
    for sid in range(NUM_SCREENS):
        due = start_t + random.uniform(0.0, max(0.01, POLL_MAX))
        heapq.heappush(heap, (due, sid))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        inflight = {}

        while True:
            now = time.perf_counter()
            if now >= end_t and not inflight:
                break

            while heap and len(inflight) < MAX_INFLIGHT:
                due, sid = heap[0]
                if due > now:
                    break
                heapq.heappop(heap)
                fut = ex.submit(_one_poll, sid, local_versions[sid])
                inflight[fut] = sid

            if inflight:
                done, _ = wait(inflight.keys(), timeout=0.05, return_when=FIRST_COMPLETED)
                for fut in done:
                    sid = inflight.pop(fut)
                    code, latency_ms, new_version, fetch_required, snap_code = fut.result()

                    stats["requests"] += 1
                    stats["latencies"].append(latency_ms)

                    if code == 304:
                        stats["304"] += 1
                    elif code == 200:
                        stats["200_update"] += 1
                    else:
                        # 0 or 4xx/5xx
                        stats["errors"] += 1

                    if fetch_required:
                        stats["snapshots"] += 1
                        if snap_code is not None and int(snap_code) >= 400:
                            stats["errors"] += 1

                    local_versions[sid] = int(new_version)

                    next_due = time.perf_counter() + random.uniform(POLL_MIN, POLL_MAX)
                    heapq.heappush(heap, (next_due, sid))
            else:
                if heap:
                    sleep_s = max(0.0, min(0.05, heap[0][0] - time.perf_counter()))
                    if sleep_s:
                        time.sleep(sleep_s)
    
    print("\n--- Load Test Results ---")
    print(f"Total Requests: {stats['requests']}")
    try:
        rps = float(stats["requests"]) / float(DURATION_SEC)
        print(f"Approx Status RPS: {rps:.2f}")
    except Exception:
        pass
    print(f"Status 304 (No Change): {stats['304']}")
    print(f"Status 200 (Updates): {stats['200_update']}")
    print(f"Snapshots Fetched: {stats['snapshots']}")
    print(f"Errors: {stats['errors']}")
    
    if stats['latencies']:
        lats = sorted(stats['latencies'])
        avg_lat = sum(lats) / len(lats)
        p95 = lats[int(0.95 * (len(lats) - 1))]
        p99 = lats[int(0.99 * (len(lats) - 1))]
        print(f"Avg Latency: {avg_lat:.2f} ms")
        print(f"p95 Latency: {p95:.2f} ms")
        print(f"p99 Latency: {p99:.2f} ms")

    reqs = max(1, stats['requests'])
    err_rate = (stats['errors'] / reqs) * 100.0
    print(f"Error rate: {err_rate:.2f}%")

    end_metrics = _metrics_snapshot()
    if start_metrics and end_metrics:
        print("\n--- Server Metrics Delta (/api/display/metrics/) ---")
        keys = [k for k in start_metrics.keys() if k.startswith("metrics:status:")]
        delta = {}
        for k in keys:
            try:
                delta[k] = int(end_metrics.get(k, 0)) - int(start_metrics.get(k, 0))
            except Exception:
                delta[k] = 0
        print(delta)

        try:
            db_qps = float(delta.get("metrics:status:rev_db", 0)) / float(DURATION_SEC)
            cache_ops_ps = float(delta.get("metrics:status:cache_get", 0) + delta.get("metrics:status:cache_set", 0)) / float(DURATION_SEC)
            denom = float(delta.get("metrics:status:rev_cache_hit", 0) + delta.get("metrics:status:rev_db", 0))
            hit_ratio = (float(delta.get("metrics:status:rev_cache_hit", 0)) / denom) if denom > 0 else 0.0
            print("--- Derived ---")
            print({
                "status_db_rev_qps": round(db_qps, 4),
                "approx_cache_ops_per_sec": round(cache_ops_ps, 2),
                "rev_cache_hit_ratio": round(hit_ratio, 4),
                "cache_backend": end_metrics.get("cache_backend"),
            })
        except Exception:
            pass

if __name__ == "__main__":
    # Ensure URL is reachable
    print("Ensure your Django server is running locally on port 8000")
    print("Ensure redis is running (optional; required if you want real Redis ops)")
    run_load_test()
