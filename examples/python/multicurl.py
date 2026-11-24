#!/usr/bin/env python3

import multiprocessing
from contextlib import closing

import commands


def foo(x):
    res = commands.getoutput("curl localhost:8888/")
    print(res)


if __name__ == "__main__":
    with closing(multiprocessing.Pool(3)) as p:
        p.map(foo, [1, 2, 3])
        p.terminate()
