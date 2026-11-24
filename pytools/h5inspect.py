#!/usr/bin/env python

import argparse
import sys
from pathlib import Path

import h5py
from colorstrings import blue_str, print_blue, red_str

tab = "  "


def show_time(thing, tabs):
    first = thing[0]
    last = thing[-1]
    dur = last - first
    msg = tab * tabs + f"[{first} - {last}] ({dur}s)"
    print(msg)


def show(name, thing, tabs, full=False):
    if "Group" not in str(type(thing)):
        print(red_str(tab * tabs + name + ": ") + str(thing))
        if "time" in name:
            show_time(thing, tabs)
        # if full:
        #    for k in thing:
        #        print(k)
        return

    print(tab * tabs + f"{name}:")
    attrs = thing.attrs.items()
    focus = full or "cv_skeleton" in str(list(attrs))
    if len(attrs) > 0:
        print_blue(tab * tabs + "Attrs:")
        for k, v in attrs:
            v = str(v)
            if len(v) > 50 and not args.no_trunc:
                v = v[0:50].replace("\n", "\\n") + "..."
            print(blue_str(tab * tabs + f"{k:25}"), v)

    for subthing in thing.keys():
        # print(f"{tab * tabs}{subthing}:")
        show(subthing, thing[subthing], tabs + 1, full=focus)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        type=str,
        help="The file",
    )
    parser.add_argument(
        "--no-trunc",
        action="store_true",
        help="dont truncate strings",
    )
    args = parser.parse_args()
    if not Path(args.path).exists():
        print("File not found")
        sys.exit(1)
    f = h5py.File(args.path, "r")

    print(f)
    attrs = f.attrs.items()
    if len(attrs) > 0:
        print_blue("Attrs:")
        for k, v in attrs:
            v = str(v)
            if len(v) > 50 and not args.no_trunc:
                v = v[0:50].replace("\n", "\\n") + "..."
            print(blue_str(f"{k:25}"), v)
    print(f.keys())

    for key in f.keys():
        print(f"\n=== {key} ===")
        show(key, f[key], 0)
