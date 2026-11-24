#!/usr/bin/env python

import os
import sys

from srutils import cmd

for path in sys.argv[1:]:
    for root, dir, files in os.walk(path):
        day = 1
        hour = 1
        print(root)
        for f in sorted(files):
            path = os.path.join(root, f)
            if not path.endswith("jpg"):
                continue
            folder = path.split("/")[0]
            start = folder.split(" ")[1].split("-")
            month = start[0]
            year = start[1]
            if len(year) == 2:
                year = f"19{year}"
            assert int(year) > 1980 and int(year) < 2015
            full_date = f"{year}:{month}:{day:02} {hour}:01:01-04:00"
            hour += 1
            if hour > 22:
                hour = 1
                day += 1
            print(path, full_date)
            print(cmd(f'exiftool "-CreateDate={full_date}" "{path}"'))
            os.remove(f"{path}_original")
