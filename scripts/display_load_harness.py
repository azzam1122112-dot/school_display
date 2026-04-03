import argparse
import heapq
import json
import os
import random
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from urllib.error import HTTPError


PROFILE_PRESETS = {
    "1k": {"num_screens": 1000, "duration_sec": 180, "poll_min": 8.0, "poll_max": 20.0, "max_workers": 200, "max_inflight": 400},
    "5k": {"num_screens": 5000, "duration_sec": 300, "poll_min": 10.0, "poll_max": 25.0, "max_workers": 300, "max_inflight": 700},
    "10k": {"num_screens": 10000, "duration_sec": 420, "poll_min": 12.0, "poll_max": 30.0, "max_workers": 400, "max_inflight": 1000},
}


def _http_get(url: str, timeout: float = 8.0, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        return exc.code, body


def _json_get(url: str, timeout: float = 5.0, headers: dict | None = None):
    code, body = _http_get(url, timeout=timeout, headers=headers)
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        payload = {}
    return code, payload


def _metrics_snapshot(base_url: str, metrics_key: str):
    headers = {"Accept": "application/json"}
    if metrics_key:
        headers["X-Display-Metrics-Key"] = metrics_key

    metrics = {}
    ws_metrics = {}
    code, payload = _json_get(f"{base_url}/api/display/metrics/", headers=headers)
    if code == 200:
        metrics = payload
    code, payload = _json_get(f"{base_url}/api/display/ws-metrics/", headers=headers)
    if code == 200:
        ws_metrics = payload
    return {"metrics": metrics, "ws_metrics": ws_metrics}


def _one_screen_poll(base_url: str, token: str, screen_id: int, local_revision: int):
    device_id = f"load-harness-{screen_id}"
    started = time.perf_counter()
    status_url = f"{base_url}/api/display/status/?token={token}&v={local_revision}&dk={device_id}"
    code, body = _http_get(status_url, timeout=6.0)
    latency_ms = (time.perf_counter() - started) * 1000.0

    if code == 304:
        return {"status_code": 304, "latency_ms": latency_ms, "revision": local_revision, "snapshot_code": None}

    payload = {}
    if code == 200:
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            payload = {}

    revision = int(payload.get("schedule_revision") or local_revision or 0)
    snapshot_code = None
    if code == 200 and bool(payload.get("fetch_required")):
        snapshot_url = f"{base_url}/api/display/snapshot/?token={token}&dk={device_id}"
        snapshot_code, _ = _http_get(snapshot_url, timeout=10.0)

    return {
        "status_code": code,
        "latency_ms": latency_ms,
        "revision": revision,
        "snapshot_code": snapshot_code,
    }


def _run_phase(name: str, *, base_url: str, token: str, metrics_key: str, profile: dict, local_versions: list[int]):
    print(f"\n=== Phase: {name} ===")
    print(profile)

    stats = {
        "requests": 0,
        "status_304": 0,
        "status_200": 0,
        "snapshots": 0,
        "errors": 0,
        "latencies": [],
    }
    started = time.perf_counter()
    finished_at = started + float(profile["duration_sec"])

    heap = []
    for sid in range(int(profile["num_screens"])):
        due = started + random.uniform(0.0, max(0.01, float(profile["poll_max"])))
        heapq.heappush(heap, (due, sid))

    with ThreadPoolExecutor(max_workers=int(profile["max_workers"])) as executor:
        inflight = {}
        while True:
            now = time.perf_counter()
            if now >= finished_at and not inflight:
                break

            while heap and len(inflight) < int(profile["max_inflight"]):
                due, sid = heap[0]
                if due > now:
                    break
                heapq.heappop(heap)
                fut = executor.submit(_one_screen_poll, base_url, token, sid, local_versions[sid])
                inflight[fut] = sid

            if inflight:
                done, _ = wait(inflight.keys(), timeout=0.05, return_when=FIRST_COMPLETED)
                for fut in done:
                    sid = inflight.pop(fut)
                    result = fut.result()

                    stats["requests"] += 1
                    stats["latencies"].append(float(result["latency_ms"]))

                    if int(result["status_code"]) == 304:
                        stats["status_304"] += 1
                    elif int(result["status_code"]) == 200:
                        stats["status_200"] += 1
                    else:
                        stats["errors"] += 1

                    if result.get("snapshot_code") is not None:
                        stats["snapshots"] += 1
                        if int(result["snapshot_code"]) >= 400:
                            stats["errors"] += 1

                    local_versions[sid] = int(result["revision"] or 0)
                    next_due = time.perf_counter() + random.uniform(float(profile["poll_min"]), float(profile["poll_max"]))
                    heapq.heappush(heap, (next_due, sid))
            else:
                if heap:
                    sleep_s = max(0.0, min(0.05, heap[0][0] - time.perf_counter()))
                    if sleep_s:
                        time.sleep(sleep_s)

    elapsed = max(1.0, time.perf_counter() - started)
    stats["rps"] = round(float(stats["requests"]) / elapsed, 2)
    if stats["latencies"]:
        lats = sorted(stats["latencies"])
        stats["avg_ms"] = round(sum(lats) / len(lats), 2)
        stats["p95_ms"] = round(lats[int(0.95 * (len(lats) - 1))], 2)
        stats["p99_ms"] = round(lats[int(0.99 * (len(lats) - 1))], 2)
    else:
        stats["avg_ms"] = 0.0
        stats["p95_ms"] = 0.0
        stats["p99_ms"] = 0.0

    snap = _metrics_snapshot(base_url, metrics_key)
    print({
        "phase": name,
        "requests": stats["requests"],
        "status_304": stats["status_304"],
        "status_200": stats["status_200"],
        "snapshots": stats["snapshots"],
        "errors": stats["errors"],
        "rps": stats["rps"],
        "avg_ms": stats["avg_ms"],
        "p95_ms": stats["p95_ms"],
        "p99_ms": stats["p99_ms"],
        "server_metrics": snap["metrics"],
        "ws_metrics": snap["ws_metrics"],
    })
    return stats


def _trigger_local_burst(manage_py: str, school_id: int, count: int, interval_ms: int):
    cmd = [sys.executable, manage_py, "trigger_display_burst", "--school-id", str(school_id), "--count", str(count), "--interval-ms", str(interval_ms)]
    return subprocess.Popen(cmd)


def _trigger_remote_hook(url: str):
    code, body = _http_get(url, timeout=10.0)
    print({"hook_url": url, "status": code, "body": body[:200].decode("utf-8", errors="ignore")})


def main():
    parser = argparse.ArgumentParser(description="Display fleet load-test harness")
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.getenv("TOKEN", ""))
    parser.add_argument("--profile", choices=sorted(PROFILE_PRESETS.keys()), default=os.getenv("PROFILE", "1k"))
    parser.add_argument("--scenario", choices=["steady", "invalidation-burst", "restart-storm"], default=os.getenv("SCENARIO", "steady"))
    parser.add_argument("--metrics-key", default=os.getenv("DISPLAY_METRICS_KEY", "").strip())
    parser.add_argument("--manage-py", default=os.getenv("MANAGE_PY", "manage.py"))
    parser.add_argument("--school-id", type=int, default=int(os.getenv("SCHOOL_ID", "0") or 0))
    parser.add_argument("--burst-count", type=int, default=int(os.getenv("BURST_COUNT", "25") or 25))
    parser.add_argument("--burst-interval-ms", type=int, default=int(os.getenv("BURST_INTERVAL_MS", "100") or 100))
    parser.add_argument("--invalidate-hook-url", default=os.getenv("INVALIDATE_HOOK_URL", ""))
    parser.add_argument("--restart-hook-url", default=os.getenv("RESTART_HOOK_URL", ""))
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("TOKEN is required.")

    profile = dict(PROFILE_PRESETS[args.profile])
    local_versions = [0] * int(profile["num_screens"])

    print({
        "scenario": args.scenario,
        "profile": args.profile,
        "base_url": args.base_url,
        "num_screens": profile["num_screens"],
    })

    baseline = _metrics_snapshot(args.base_url, args.metrics_key)
    print({"baseline_metrics": baseline})

    _run_phase("warmup", base_url=args.base_url, token=args.token, metrics_key=args.metrics_key, profile=profile, local_versions=local_versions)

    if args.scenario == "invalidation-burst":
        if args.invalidate_hook_url:
            _trigger_remote_hook(args.invalidate_hook_url)
        elif args.school_id > 0:
            proc = _trigger_local_burst(args.manage_py, args.school_id, args.burst_count, args.burst_interval_ms)
            proc.wait(timeout=120)
        else:
            print("No invalidation hook configured. Supply --school-id for local runs or --invalidate-hook-url for remote.")
        _run_phase("burst-recovery", base_url=args.base_url, token=args.token, metrics_key=args.metrics_key, profile=profile, local_versions=local_versions)
    elif args.scenario == "restart-storm":
        if args.restart_hook_url:
            _trigger_remote_hook(args.restart_hook_url)
        else:
            print("Trigger your deploy/restart now, then observe the recovery phase.")
            time.sleep(10)
        _run_phase("post-restart-recovery", base_url=args.base_url, token=args.token, metrics_key=args.metrics_key, profile=profile, local_versions=local_versions)
    else:
        _run_phase("steady", base_url=args.base_url, token=args.token, metrics_key=args.metrics_key, profile=profile, local_versions=local_versions)

    final_snap = _metrics_snapshot(args.base_url, args.metrics_key)
    print({"final_metrics": final_snap})


if __name__ == "__main__":
    main()
