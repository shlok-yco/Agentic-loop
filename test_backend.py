import requests
import time
import uuid
import threading
import logging

logging.basicConfig(level=logging.INFO, filename="logs/test_backend.log", filemode="a")
run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"


def run_post():
    try:
        print("POST /run")
        res = requests.post(
            "http://localhost:5000/run",
            json={
                "user_query": "Which channel creates the best balance between customer acquisition, revenue generation, and profitability?",
                "data_path": "/home/shlok.koirala/denzing/my_experiments/agentic/CSVs/Retail data 1.csv",
                "run_id": run_id,
            },
        )
        print("POST /run returned:", res.status_code)
    except Exception as e:
        print("POST /run failed:", e)


t = threading.Thread(target=run_post)
t.start()

while True:
    time.sleep(10)
    try:
        res = requests.get(f"http://localhost:5000/status/{run_id}")
        logging.info(f"GET /status returned: {res.status_code} {res.text}")
    except Exception as e:
        logging.info("GET /status failed: %s", e)

t.join()
