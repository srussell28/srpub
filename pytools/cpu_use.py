#!/usr/bin/env python3

import sys
import time

from srutils import cmd


def is_int(x):
    try:
        int(x)
        return True
    except Exception:
        return False


def get_pid(wat):
    # Assume ints are process ids
    if is_int(wat):
        return int(wat)

    # assume strings are process names
    proc_name = wat

    pid = cmd(f"pidof {proc_name}")
    if pid:
        return pid

    print("waiting for process to start...")
    while not pid:
        time.sleep(1)
        pid = cmd(f"pidof {proc_name}")

    return pid


if __name__ == "__main__":
    ema = 0.85
    avg = None
    t0 = time.time()

    # print("time\tcur\tavg")
    print("CPU %")
    while True:
        pid = get_pid(sys.argv[1])
        if not pid:
            print("No Pid")
            time.sleep(0.25)
            continue

        r = cmd(f"ps -p {pid} -o %cpu")
        # print(r.split("\n"))
        cpu = float(r.split("\n")[1])
        if avg is None:
            avg = cpu
        else:
            avg = (ema * avg) + ((1 - ema) * cpu)
        # print("%.1f\t%.1f\t%.1f" % ((time.time() - t0), cpu, avg))
        print(f"{cpu} %")
        time.sleep(0.25)
