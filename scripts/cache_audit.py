"""End-to-end cache audit for School Display.

This script performs *measured* checks:
- Redis reachability via /api/display/metrics/ (redis_ping_ok)
- Shared-cache probe across workers (/api/display/metrics/?probe=1)
- Snapshot warmup/hit-rate (/api/display/snapshot/<token>/?dk=<uuid>)
- Cache-Control headers (edge caching eligibility) and Cloudflare headers if present

Usage (PowerShell):
  $env:BASE_URL='https://your-domain.example.com'
  $env:METRICS_KEY='...'
  $env:DISPLAY_TOKEN='...'
  $env:DEVICE_KEY='550e8400-e29b-41d4-a716-446655440000'
  python scripts/cache_audit.py

Optional:
  $env:ORIGIN_URL='https://school-display-p8ec.onrender.com'  # to compare CF vs origin

Notes:
- BASE_URL should be the Cloudflare-fronted domain if you want CF headers.
- This script does not enable metrics; you must set DISPLAY_METRICS_ENABLED=1 and DISPLAY_METRICS_KEY on the server.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class Result:
    name: str
    ok: bool
    evidence: str


@dataclass
class SnapshotPair:
    first: requests.Response
    second: requests.Response


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default


def _require(name: str) -> str:
    v = _env(name)
    if not v:
        raise SystemExit(f"Missing env var: {name}")
    return v


def _urljoin(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def _get_json(session: requests.Session, url: str, *, headers: dict[str, str] | None = None, timeout: int = 15) -> dict[str, Any]:
    r = session.get(url, headers=headers, timeout=timeout)
    ct = (r.headers.get("content-type") or "").lower()
    if r.status_code >= 400:
        raise RuntimeError(f"GET {url} -> {r.status_code}: {r.text[:300]}")
    if "application/json" not in ct:
        raise RuntimeError(f"GET {url} -> {r.status_code} non-json content-type={ct}")
    return r.json()


def _get(session: requests.Session, url: str, *, headers: dict[str, str] | None = None, timeout: int = 15) -> requests.Response:
    return session.get(url, headers=headers, timeout=timeout)


def _head(session: requests.Session, url: str, *, headers: dict[str, str] | None = None, timeout: int = 15) -> requests.Response:
    return session.head(url, headers=headers, timeout=timeout)


def _fmt_headers(h: dict[str, str], keys: list[str]) -> str:
    parts: list[str] = []
    for k in keys:
        v = h.get(k)
        if v is None:
            v = h.get(k.lower())
        if v:
            parts.append(f"{k}={v}")
    return "; ".join(parts)


def _pick(h: dict[str, str], key: str) -> str:
    v = h.get(key)
    if v is None:
        v = h.get(key.lower())
    return (v or "").strip()


def _snapshot_headers_evidence(r: requests.Response) -> str:
    h = r.headers
    return " ".join(
        [
            f"status={r.status_code}",
            f"Cache-Control={_pick(h, 'Cache-Control')}",
            f"X-Snapshot-Cache={_pick(h, 'X-Snapshot-Cache')}",
            f"CF-Cache-Status={_pick(h, 'CF-Cache-Status')}",
            f"Age={_pick(h, 'Age')}",
            f"CF-Ray={_pick(h, 'CF-Ray')}",
        ]
    ).strip()


def _get_twice(session: requests.Session, url: str, *, timeout: int = 20) -> SnapshotPair:
    # Do two full GET requests (not HEAD) to exercise edge caching.
    r1 = session.get(url, timeout=timeout)
    r2 = session.get(url, timeout=timeout)
    return SnapshotPair(first=r1, second=r2)


def main() -> int:
    base_url = _require("BASE_URL")
    metrics_key = _require("METRICS_KEY")
    display_token = _require("DISPLAY_TOKEN")
    device_key = _require("DEVICE_KEY")
    origin_url = _env("ORIGIN_URL")

    session = requests.Session()

    metrics_headers = {
        "X-Display-Metrics-Key": metrics_key,
        "User-Agent": "cache-audit/1.0",
    }

    results: list[Result] = []

    # 1) Fetch metrics once (sanity + redis ping)
    metrics_url = _urljoin(base_url, "/api/display/metrics/")
    try:
        m0 = _get_json(session, metrics_url, headers=metrics_headers)
        # We keep this as supporting evidence; the requested PASS/FAIL focuses on shared-cache/snapshot/edge.
    except Exception as e:
        m0 = {}

    # 2) Shared-cache probe across workers
    probe_url = _urljoin(base_url, "/api/display/metrics/?probe=1")
    rows: list[dict[str, Any]] = []
    pids: set[int] = set()
    missing_last = 0

    for i in range(20):
        try:
            mi = _get_json(session, probe_url, headers=metrics_headers)
            rows.append(mi)
            pid = int(mi.get("process_id") or 0)
            if pid:
                pids.add(pid)
            if mi.get("cache_probe_last") in (None, "", 0):
                missing_last += 1
        except Exception as e:
            rows.append({"error": str(e)})
        time.sleep(0.15)

    shared_ok = (len(pids) >= 2) and (missing_last == 0)
    if len(pids) < 2:
        results.append(
            Result(
                "Redis shared-cache",
                False,
                "Only one process_id observed in 20 probes; cannot prove cross-worker sharing. Ensure WEB_CONCURRENCY>1 and verify load-balancing.",
            )
        )
    else:
        results.append(
            Result(
                "Redis shared-cache",
                shared_ok,
                f"process_ids={sorted(pids)} missing_cache_probe_last={missing_last}/20 redis_ping_ok={m0.get('redis_ping_ok')} cache_backend={m0.get('cache_backend')}",
            )
        )

    # 3) Snapshot warmup/hit rate
    snap_url = _urljoin(base_url, f"/api/display/snapshot/{display_token}/?dk={device_key}")
    m_before = {}
    m_after = {}
    try:
        m_before = _get_json(session, metrics_url, headers=metrics_headers)
    except Exception:
        pass

    caches: list[str] = []
    statuses: list[int] = []
    for i in range(30):
        r = _get(session, snap_url, timeout=20)
        statuses.append(int(r.status_code))
        caches.append((r.headers.get("X-Snapshot-Cache") or "").strip())
        time.sleep(0.2)

    try:
        m_after = _get_json(session, metrics_url, headers=metrics_headers)
    except Exception:
        pass

    def _delta(key: str) -> int | None:
        if not m_before or not m_after:
            return None
        try:
            return int(m_after.get(key, 0) or 0) - int(m_before.get(key, 0) or 0)
        except Exception:
            return None

    # Expect at least some HITs after warmup.
    hit_count = sum(1 for c in caches if c == "HIT")
    miss_count = sum(1 for c in caches if c == "MISS")
    stale_count = sum(1 for c in caches if c == "STALE")
    bypass_count = sum(1 for c in caches if c == "BYPASS")

    # Build count should not grow ~linearly with requests.
    build_delta = _delta("metrics:snapshot_cache:build_count")
    school_hit_delta = _delta("metrics:snapshot_cache:school_hit")
    token_hit_delta = _delta("metrics:snapshot_cache:token_hit")

    snapshot_ok = (hit_count >= 20) and (build_delta is None or build_delta <= 5)
    results.append(
        Result(
            "Snapshot build behavior",
            snapshot_ok,
            f"status_codes={set(statuses)} X-Snapshot-Cache: HIT={hit_count} MISS={miss_count} STALE={stale_count} BYPASS={bypass_count} "
            f"deltas(build_count={build_delta}, school_hit={school_hit_delta}, token_hit={token_hit_delta})",
        )
    )

    # 4) Cloudflare edge caching proof (double GET):
    # - BASE_URL (Cloudflare) should show CF-Cache-Status=HIT on second response and Age header.
    # - ORIGIN_URL (Render direct) should not show CF headers.
    cf_pair = _get_twice(session, snap_url, timeout=20)
    cf1 = _snapshot_headers_evidence(cf_pair.first)
    cf2 = _snapshot_headers_evidence(cf_pair.second)

    cf_status_2 = _pick(cf_pair.second.headers, "CF-Cache-Status")
    age_2 = _pick(cf_pair.second.headers, "Age")

    # Cloudflare eligibility conditions
    cc2 = _pick(cf_pair.second.headers, "Cache-Control")
    has_smaxage = "s-maxage=" in cc2
    cf_hit = (cf_status_2.upper() == "HIT")
    age_present = bool(age_2)

    origin_ok = True
    origin_evidence = "ORIGIN_URL not provided"
    if origin_url:
        origin_snap_url = _urljoin(origin_url, f"/api/display/snapshot/{display_token}/?dk={device_key}")
        o_pair = _get_twice(session, origin_snap_url, timeout=20)
        o1 = _snapshot_headers_evidence(o_pair.first)
        o2 = _snapshot_headers_evidence(o_pair.second)
        # Expect no CF headers on origin.
        origin_ok = (not _pick(o_pair.second.headers, "CF-Cache-Status")) and (not _pick(o_pair.second.headers, "CF-Ray"))
        origin_evidence = f"origin_1: {o1} | origin_2: {o2}"

    edge_ok = has_smaxage and cf_hit and age_present and origin_ok
    results.append(
        Result(
            "Cloudflare edge caching",
            edge_ok,
            f"cf_1: {cf1} | cf_2: {cf2} | origin_check: {origin_evidence}",
        )
    )

    # Print report
    print("\n=== CACHE AUDIT REPORT (PASS/FAIL) ===")
    for res in results:
        status = "PASS" if res.ok else "FAIL"
        print(f"[{status}] {res.name}: {res.evidence}")

    # Evidence samples (probe rows)
    print("\n--- Probe samples (first 10) ---")
    for row in rows[:10]:
        if "error" in row:
            print(f"error={row['error']}")
            continue
        print(
            " ".join(
                [
                    f"host={row.get('hostname')}",
                    f"pid={row.get('process_id')}",
                    f"backend={row.get('cache_backend')}",
                    f"last={row.get('cache_probe_last')}",
                    f"written={row.get('cache_probe_written')}",
                    f"redis_ping_ok={row.get('redis_ping_ok')}",
                ]
            )
        )

    # Exit code: non-zero if any FAIL
    return 1 if any(not r.ok for r in results) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
