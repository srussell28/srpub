#!/usr/bin/env python3


class MyClass:
    def __init__(self):
        pass

    def __getattribute__(self, name):
        print("request for attr " + str(name))
        if name == "bak":
            return "I drink your milkshake"

        return object.__getattribute__(self, name)

    @property
    def foo(self):
        return "womp foo"

    @property
    def bak(self):
        return "womp bak"

    @property
    def bar(self):
        return "womp bar"


c = MyClass()

print(c.foo)
print(c.bak)
print(c.bar)
