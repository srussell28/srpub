#!/usr/bin/env python3

import re

target = "poo"


def womp(m):
    global target
    print(
        "im in womp target is "
        + str(target)
        + " >"
        + m.group(0)
        + "< >"
        + m.group(1)
        + "< >"
        + str(m.group(2))
        + "<"
    )
    return "func(" + m.group(1) + target + "_pop" + m.group(2) + ")"
    # return "works"


text = "This is some func(apple, banana) banana func(grape, banana, orange) func(grape)"
print(text)

target = "banana"

res = re.sub(r"func\((.*?)" + target + r"(.*?)\)", womp, text)

print(res)
