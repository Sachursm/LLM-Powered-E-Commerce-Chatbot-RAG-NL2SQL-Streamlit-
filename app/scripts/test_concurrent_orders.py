import requests
from concurrent.futures import ThreadPoolExecutor

BASE_URL = "http://127.0.0.1:8000"

USER1_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwicm9sZSI6IlVTRVIiLCJleHAiOjE3ODg1MjkyMjF9.qyrMUm_o1V0wkJnrGdp_Ij2NkY0Toc8gcJgh0ivcneM"
USER2_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyIiwicm9sZSI6IlNFTExFUiIsImV4cCI6MTc4ODUyOTE4NX0.GYviwfQ-rkVHSB6SGA-DljQsNEWKX19TL6VEQfPvZL8"


def create_order(name, token):
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            f"{BASE_URL}/orders",
            headers=headers,
            timeout=10,
        )

        print(f"\n{name}")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")

        return response.status_code

    except Exception as e:
        print(f"\n{name} ERROR: {e}")
        return None


# Send both requests concurrently
with ThreadPoolExecutor(max_workers=2) as executor:
    future1 = executor.submit(
        create_order,
        "USER 1",
        USER1_TOKEN
    )

    future2 = executor.submit(
        create_order,
        "USER 2",
        USER2_TOKEN
    )

    result1 = future1.result()
    result2 = future2.result()


print("\n==============================")
print("CONCURRENCY TEST RESULT")
print("==============================")
print(f"User 1 status: {result1}")
print(f"User 2 status: {result2}")