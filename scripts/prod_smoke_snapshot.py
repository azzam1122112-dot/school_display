"""Production smoke check for School Display snapshot API.

Usage:
  python scripts/prod_smoke_snapshot.py --base https://school-display-p8ec.onrender.com --token <TOKEN> --device <DEVICE>

What it checks:
- 200 + JSON shape
- ETag present
- 304 behavior on If-None-Match
- X-Snapshot-Cache header (HIT/MISS/STALE/BYPASS)
- State type (active window vs steady)

This script is safe: it does NOT write data; it only does GET requests.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import requests


def _jget(d: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
    return cur if cur is not None else default


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="Base URL, e.g. https://school-display-p8ec.onrender.com")
    ap.add_argument("--token", required=True, help="Display token")
    ap.add_argument("--device", default="smoke-devA", help="Device key/header")
    ap.add_argument("--n", type=int, default=5, help="Number of requests")
    ap.add_argument("--sleep", type=float, default=1.0, help="Delay between requests")
    ap.add_argument(
        "--expect-active-window",
        action="store_true",
        help="Fail if meta.is_active_window is not true (useful for morning checks)",
    )
    ap.add_argument(
        "--expect-state",
        default="",
        help="Comma-separated allowed state.type values (e.g. period,before,NO_SCHEDULE_TODAY)",
    )
    args = ap.parse_args()

    base = args.base.rstrip("/")
    url = f"{base}/api/display/snapshot/{args.token}/"

    s = requests.Session()
    etag = None

    status_counts: dict[int, int] = {}
    cache_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    total_ms = 0
    total_reqs = 0

    def print_summary() -> None:
        c200 = status_counts.get(200, 0)
        c304 = status_counts.get(304, 0)
        hit = cache_counts.get("HIT", 0)
        miss = cache_counts.get("MISS", 0)
        stale = cache_counts.get("STALE", 0)
        bypass = cache_counts.get("BYPASS", 0)
        total_cache = hit + miss + stale + bypass

        hit_rate = (hit / total_cache) if total_cache else 0.0
        avg_ms = int(total_ms / total_reqs) if total_reqs else 0

        top_state = None
        if state_counts:
            top_state = max(state_counts.items(), key=lambda kv: kv[1])

        print("\nSummary")
        print(f"  requests={total_reqs} avg_ms={avg_ms}")
        print(f"  status: 200={c200} 304={c304} other={max(0, total_reqs - c200 - c304)}")
        print(
            f"  cache: HIT={hit} MISS={miss} STALE={stale} BYPASS={bypass} hit_rate={hit_rate:.0%}"
        )
        if top_state:
            print(f"  top_state: {top_state[0]!r} x{top_state[1]}")

    print(f"URL: {url}")
    print(f"Device: {args.device}")

    expected_states = {
        s.strip() for s in (args.expect_state or "").split(",") if s.strip()
    }

    for i in range(args.n):
        headers = {
            "X-Display-Device": args.device,
            # Encourage 304 path
            "If-None-Match": etag or "",
        }

        t0 = time.time()
        r = s.get(url, headers=headers, timeout=20)
        dt_ms = int((time.time() - t0) * 1000)

        total_reqs += 1
        total_ms += dt_ms
        status_counts[r.status_code] = status_counts.get(r.status_code, 0) + 1

        xsnap = r.headers.get("X-Snapshot-Cache")
        xbind = r.headers.get("X-Snapshot-Device-Bound")
        new_etag = r.headers.get("ETag")

        print(f"[{i+1}/{args.n}] {r.status_code} {dt_ms}ms  X-Snapshot-Cache={xsnap}  Bound={xbind}  ETag={'yes' if new_etag else 'no'}")

        if xsnap:
            cache_counts[str(xsnap).strip().upper()] = cache_counts.get(str(xsnap).strip().upper(), 0) + 1

        if r.status_code == 304:
            # Keep previous etag
            time.sleep(max(0.0, args.sleep))
            continue

        if r.status_code != 200:
            print("Non-200 response body:")
            print(r.text[:2000])
            return 2

        try:
            body = r.json()
        except Exception:
            print("Failed to parse JSON. Body:")
            print(r.text[:2000])
            return 2

        # Basic shape checks
        required_keys = ["now", "meta", "settings", "state", "day_path", "period_classes", "standby", "excellence", "announcements"]
        missing = [k for k in required_keys if k not in body]
        if missing:
            print(f"Missing keys: {missing}")
            print(json.dumps(body, ensure_ascii=False)[:2000])
            return 2

        state_type = _jget(body, "state.type", "")
        label = _jget(body, "state.label", "")
        is_active = bool(_jget(body, "meta.is_active_window", False))
        refresh = _jget(body, "settings.refresh_interval_sec", None)

        print(f"    state.type={state_type!r} active_window={is_active} refresh_interval_sec={refresh} label={label!r}")

        st_key = str(state_type or "").strip() or "<empty>"
        state_counts[st_key] = state_counts.get(st_key, 0) + 1

        if args.expect_active_window and not is_active:
            print("Expectation failed: meta.is_active_window is false")
            print_summary()
            return 3

        if expected_states and str(state_type) not in expected_states:
            print(f"Expectation failed: state.type={state_type!r} not in {sorted(expected_states)!r}")
            print_summary()
            return 3

        # Save ETag for next round
        if new_etag:
            etag = new_etag

        time.sleep(max(0.0, args.sleep))

    print_summary()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
