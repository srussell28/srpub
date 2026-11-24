#!/usr/bin/env python3

import errno
import os
import signal
import time
from functools import wraps


class TimeoutError(Exception):
    pass


#########################
# Decorator Version
#########################


def timeout(seconds=10, error_message=os.strerror(errno.ETIME)):
    def decorator(func):
        def _handle_timeout(signum, frame):
            raise TimeoutError(error_message)

        def wrapper(*args, **kwargs):
            signal.signal(signal.SIGALRM, _handle_timeout)
            signal.alarm(seconds)
            try:
                result = func(*args, **kwargs)
            finally:
                signal.alarm(0)
            return result

        return wraps(func)(wrapper)

    return decorator


@timeout(2)
def long():
    try:
        time.sleep(15)
    except TimeoutError:
        raise
    except Exception:
        print("wopps caught")


print("running the decorator version")
try:
    long()
except TimeoutError:
    print("long timed out")

#########################
# Context Manager Version
#########################

import contextlib2


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


print("\n\nrunning the context manager version")
with ctxtimeout(2):
    time.sleep(15)
    print("never makes it")
