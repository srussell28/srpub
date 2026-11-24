#!/usr/bin/env python3

import datetime
import time
from unittest import mock

import schedule_vol


def test_interp():
    fake_time = datetime.datetime.now()
    schedule_vol.get_now = mock.MagicMock(return_value=fake_time)

    v = schedule_vol.Volumizer()
    for i in range(1000):
        fake_time = fake_time + datetime.timedelta(minutes=5)
        schedule_vol.get_now = mock.MagicMock(return_value=fake_time)
        v.update()
        if i == 30:
            print("booosting")
            v.apply_boost(3)
        time.sleep(0.1)


if __name__ == "__main__":
    test_interp()
