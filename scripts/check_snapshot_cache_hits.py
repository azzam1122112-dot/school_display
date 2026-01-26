from __future__ import annotations

import os
import time
from typing import Any

import requests


def _get_env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _metrics(base_url: str, headers: dict[str, str]) -> dict[str, Any] | None:
    url = f"{base_url.rstrip('/')}/api/display/metrics/"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _status_revision(base_url: str, token: str, dk: str) -> int | None:
    url = f"{base_url.rstrip('/')}/api/display/status/{token}/"
    try:
        # force numeric path; v=0 means "client has nothing"
        r = requests.get(url, params={"dk": dk, "v": "0"}, timeout=10)
        if r.status_code == 200:
            j = r.json()
            v = j.get("schedule_revision")
            return int(v) if v is not None else None
        # If 304 somehow returned, read from header.
        if r.status_code == 304:
            h = (r.headers.get("X-Schedule-Revision") or "").strip()
            return int(h) if h.isdigit() else None
        return None
    except Exception:
        return None


def main() -> int:
    base_url = _get_env("BASE_URL", "http://127.0.0.1:8000")
    token = _get_env("TOKEN")
    dk = _get_env("DK")
    count = int(_get_env("COUNT", "5") or "5")
    sleep_sec = float(_get_env("SLEEP_SEC", "0.2") or "0.2")

    metrics_key = _get_env("DISPLAY_METRICS_KEY")
    metrics_headers: dict[str, str] = {}
    if metrics_key:
        metrics_headers["X-Display-Metrics-Key"] = metrics_key

    if not token or not dk:
        print("Missing TOKEN or DK env vars.")
        print("Example:")
        print("  set BASE_URL=https://<your-host>")
        print("  set TOKEN=<display token>")
        print("  set DK=<device key>")
        return 2

    before = _metrics(base_url, metrics_headers) or {}

    rev = _status_revision(base_url, token, dk)
    print(f"base_url={base_url}")
    print(f"token_prefix={token[:8]}...")
    print(f"dk={dk}")
    print(f"status_rev={rev}")

    snap_url = f"{base_url.rstrip('/')}/api/display/snapshot/{token}/"

    for i in range(1, count + 1):
        try:
            r = requests.get(snap_url, params={"dk": dk}, timeout=20)
            cache_hdr = (r.headers.get("X-Snapshot-Cache") or "").strip()
            etag = (r.headers.get("ETag") or "").strip()
            print(f"snapshot[{i}] status={r.status_code} X-Snapshot-Cache={cache_hdr} ETag={etag}")
        except Exception as e:
            print(f"snapshot[{i}] ERROR: {e}")
        time.sleep(sleep_sec)

    after = _metrics(base_url, metrics_headers) or {}

    def _delta(k: str) -> int:
        try:
            return int(after.get(k, 0)) - int(before.get(k, 0))
        except Exception:
            return 0

    if after:
        print("metrics.cache_backend=", after.get("cache_backend"))
        print("metrics.redis_url_configured=", after.get("redis_url_configured"))

        for key in [
            "metrics:snapshot_cache:token_hit",
            "metrics:snapshot_cache:token_miss",
            "metrics:snapshot_cache:school_hit",
            "metrics:snapshot_cache:school_miss",
            "metrics:snapshot_cache:steady_hit",
            "metrics:snapshot_cache:steady_miss",
        ]:
            print(f"delta {key} = {_delta(key)}")

        print(
            "NOTE: If all HIT deltas are 0, either metrics endpoint is disabled, "
            "or cache is not shared (no Redis / multiple workers), or requests are being rejected (403)."
        )
    else:
        print("metrics endpoint not available (enable DISPLAY_METRICS_ENABLED=1 in production if needed).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
