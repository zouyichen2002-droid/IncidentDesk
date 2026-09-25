import threading
import time
import httpx


class Circuit:
    def __init__(self):
        self.lock = threading.Lock()
        self.failures = 0
        self.until = 0

    def call(self, fn):
        with self.lock:
            if time.monotonic() < self.until:
                raise RuntimeError("source_circuit_open")
        for attempt in range(3):
            try:
                r = fn()
                r.raise_for_status()
                with self.lock:
                    self.failures = 0
                    self.until = 0
                return r
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                status = (
                    e.response.status_code
                    if isinstance(e, httpx.HTTPStatusError)
                    else 0
                )
                if status and status != 429 and status < 500:
                    raise
                with self.lock:
                    self.failures += 1
                    if self.failures >= 5:
                        self.until = time.monotonic() + 10
                if attempt == 2:
                    raise
                time.sleep(0.1 * (2**attempt))
