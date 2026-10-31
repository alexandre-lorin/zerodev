import time
for i in range(10_000):
    print(f"heartbeat {i}", flush=True)
    time.sleep(2)
