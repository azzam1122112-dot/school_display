# Display Layer Architecture (Cache-First System)

## Overview
The Display Layer for school screens is engineered as a **Read-Heavy, Zero-DB-Hit** system. It decouples the administrative backend (PostgreSQL) from the thousands of connected client screens (consuming Redis Snapshots).

## Core Principles (Strict Strictness)
1.  **NO DB READS in Display API:** The endpoint `/api/display/snapshot/` must NEVER query the database. It serves purely from Redis.
2.  **Central Builder:** Any change to screen data (Schedule, Duty, Notices, Settings) MUST go through `dashboard.services_display.build_school_snapshot`.
3.  **Atomic Updates:** Updates are written via Lua Script to ensure Version/Snapshot consistency.
4.  **Client Logic:** The server provides raw data + server timestamps. Logic for "Current Period" or "Active Slide" resides in the Frontend (JS).

## Data Flow

### Write Path (Admin Action)
1.  Admin saves change (Django Admin/Form).
2.  `signals_display.py` detects change.
3.  **Debounce/Lock:** System acquires a Redis Lock to prevent concurrent builds.
4.  **Builder:** `services_display` queries DB and constructs a massive JSON dictionary.
5.  **Compress:** JSON is Gzipped.
6.  **Atomic Write:** Lua script increments `version` and sets `snapshot`.

### Read Path (Screen)
1.  **Status Check (Every 60s):**
    *   `GET /api/display/status/?token=X&v=105`
    *   Server checks Redis Version.
    *   Returns `304 Not Modified` (Normal case) or `200 JSON` (Update needed).
2.  **Snapshot Fetch:**
    *   `GET /api/display/snapshot/?token=X`
    *   Server streams Gzipped JSON from Redis directly.

## Key Files
*   **Builder:** `dashboard/services_display.py`
*   **API:** `dashboard/api_display_v2.py`
*   **Triggers:** `dashboard/signals_display.py`

## Troubleshooting
*   **Missing Data?** Check if Signals are firing for that specific model.
*   **Stale Data?** Check connection to Redis or Debounce logs.
*   **Cold Start:** If Redis is flushed, the first request will trigger a synchronous build (protected by lock).
