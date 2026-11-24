#!/usr/bin/env python3

import datetime
import time


def foo(x):
    print(x)
    return datetime.datetime.now()


print(datetime.datetime.now())

# Foo isnt executed here, its build into a special function
lf = lambda: foo(8)

time.sleep(1)

print(lf())
