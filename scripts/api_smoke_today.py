"""
Script: test_api_today.py
وظيفة السكريبت: اختبار استجابة API اليوم وعرض البيانات المعادة.
"""
import requests

token = "d3b6928eb6235dc98385ed40436951a55b1b19044dfa00ef74743e196076df42"
url = f"http://127.0.0.1:8000/api/display/today/?token={token}"

print(f"اختبار: {url}\n")
try:
    resp = requests.get(url)
    print(f"Status: {resp.status_code}")
    print("Response:")
    print(resp.json())
except Exception as e:
    print(f"❌ Error: {e}")
