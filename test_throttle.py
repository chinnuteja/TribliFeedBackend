"""Different hosts run in parallel; one host stays at 1 req/delay.
python test_throttle.py"""
import time
from concurrent.futures import ThreadPoolExecutor
from app import fetcher

fetcher.PER_HOST_DELAY = 0.4
D = fetcher.PER_HOST_DELAY


def elapsed(hosts):
    fetcher._last_hit.clear()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(hosts)) as ex:
        list(ex.map(fetcher._throttle, hosts))
    return time.time() - t0


# 4 distinct hosts: all first hits, none should wait on another
four_hosts = elapsed([f"h{i}.example" for i in range(4)])
assert four_hosts < D, f"distinct hosts serialised: {four_hosts:.2f}s"

# same host 4x: 1st is free, the other 3 each wait a full delay
one_host = elapsed(["h.example"] * 4)
assert one_host >= 3 * D * 0.9, f"same host not throttled: {one_host:.2f}s"

print(f"throttle OK  (4 hosts {four_hosts:.2f}s, 1 host x4 {one_host:.2f}s, delay {D}s)")
