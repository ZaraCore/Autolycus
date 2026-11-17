import logging
import time


def retry(operation, attempts=3, sleep=time.sleep):
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            if not getattr(exc, "retryable", False) or attempt == attempts - 1:
                raise
            logging.getLogger("autolycus").warning("临时故障，准备重试 category=%s attempt=%d", type(exc).__name__, attempt + 1)
            sleep((2, 5)[min(attempt, 1)])
