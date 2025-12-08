import requests
try:
    r = requests.get("http://127.0.0.1:8000/api/display/live/?token=d3b6928eb6235dc98385ed40436951a55b1b19044dfa00ef74743e196076df42")
    print(f"Status: {r.status_code}")
    print(f"Content: {r.text}")
except Exception as e:
    print(f"Error: {e}")
