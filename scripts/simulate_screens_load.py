import time
import threading
import random
import sys
import os

# Configuration
BASE_URL = "http://127.0.0.1:8000" # Change active server
TOKEN = "TEST_TOKEN_LOAD" # Ensure this token is in Redis/DB for testing
NUM_SCREENS = 1000
DURATION_SEC = 60
POLL_INTERVAL_RANGE = (30, 60)

# Statistics
stats = {
    "requests": 0,
    "304": 0,
    "200_update": 0,
    "snapshots": 0,
    "errors": 0,
    "latencies": []
}
print_lock = threading.Lock()

def mock_screen_behavior(screen_id):
    """
    Simulates a single screen polling loop
    """
    local_version = 0
    end_time = time.time() + DURATION_SEC
    
    # Simple Request Mock (using urllib to avoid external dependencies like requests)
    import urllib.request
    import json
    from urllib.error import HTTPError

    while time.time() < end_time:
        try:
            start_req = time.time()
            url = f"{BASE_URL}/api/display/status/?token={TOKEN}&v={local_version}"
            
            req = urllib.request.Request(url)
            try:
                with urllib.request.urlopen(req) as response:
                    latency = (time.time() - start_req) * 1000
                    stats["latencies"].append(latency)
                    stats["requests"] += 1
                    
                    if response.status == 200:
                        # Update needed
                        data = json.loads(response.read().decode())
                        server_ver = data.get("current_version", 0)
                        
                        stats["200_update"] += 1
                        
                        # Fetch Snapshot
                        snap_url = f"{BASE_URL}/api/display/snapshot/?token={TOKEN}"
                        with urllib.request.urlopen(snap_url) as snap_resp:
                            _ = snap_resp.read() # Consume
                            stats["snapshots"] += 1
                            local_version = server_ver
                            
                    elif response.status == 304:
                         stats["304"] += 1
                         
            except HTTPError as e:
                # HTTPError usually throws for 4xx/5xx, but urllib might throw for 304 depending on handler
                if e.code == 304:
                    stats["requests"] += 1
                    stats["304"] += 1
                else:
                    stats["errors"] += 1
                    
        except Exception as e:
            stats["errors"] += 1

        # Sleep with jitter
        sleep_time = random.randint(*POLL_INTERVAL_RANGE)
        time.sleep(sleep_time)

def run_load_test():
    print(f"--- Starting Load Test: {NUM_SCREENS} screens for {DURATION_SEC}s ---")
    threads = []
    
    # Start threads
    for i in range(NUM_SCREENS):
        t = threading.Thread(target=mock_screen_behavior, args=(i,))
        t.daemon = True
        threads.append(t)
        t.start()
        # Stagger start to avoid initial spike
        time.sleep(0.005) 

    # Wait for completion
    time.sleep(DURATION_SEC)
    
    print("\n--- Load Test Results ---")
    print(f"Total Requests: {stats['requests']}")
    print(f"Status 304 (No Change): {stats['304']}")
    print(f"Status 200 (Updates): {stats['200_update']}")
    print(f"Snapshots Fetched: {stats['snapshots']}")
    print(f"Errors: {stats['errors']}")
    
    if stats['latencies']:
        avg_lat = sum(stats['latencies']) / len(stats['latencies'])
        print(f"Avg Latency: {avg_lat:.2f} ms")

if __name__ == "__main__":
    # Ensure URL is reachable
    print("Ensure your Django server is running locally on port 8000")
    print("Ensure redis is running")
    run_load_test()
