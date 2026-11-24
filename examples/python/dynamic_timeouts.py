#!/usr/bin/env python3

import random
import signal
import time

import contextlib2


class TimeoutError(Exception):
    pass


@contextlib2.contextmanager
def ctxtimeout(timeout):
    """Core instrumentation logic."""

    def _handle_timeout(signum, frame):
        raise TimeoutError("asdf")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.alarm(timeout)
    try:
        yield
    finally:
        signal.alarm(0)


# A value which most requests should fall under
LOW_TIMEOUT = 0.3

# A value which all requests should fall under
HIGH_TIMEOUT = 5.0

# Percent of request allowed to exceed the low timeout before we switch to systemic failure mode
PERCENT_ALLOWED_HIGH = 0.05


def simulated_call():
    # This simulated
    t = random.random() * 0.2
    if random.random() < 0.01:
        t = 4.0

    time.sleep(t)


with ctxtimeout(HIGH_TIMEOUT):
    simulated_call()
