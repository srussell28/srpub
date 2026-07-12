"""
This solution is simple, but in-efficient because it
re-does compuation on every get-call, and because
it re-does formula evluation of common dependencies.

However this laziness lets it easily solve the 2b issues
"""

import re


class MySheet:
    def __init__(self):
        self.data = {}

    def _as_number(self, thing):
        """Try an interpret thing as a number"""
        if thing.isnumeric():
            return int(thing)

        # if its not a number, it must be a cell-addr
        assert re.match(r"^[A-Z]+\d+$", thing)

        return int(self.get(thing, default=0))

    def _eval_formula(self, v):
        terms = v.split("+")
        as_ints = [self._as_number(x.strip()) for x in terms]
        return sum(as_ints)

    def put(self, addr, value):
        self.data[addr] = str(value).strip()

    def get(self, addr, default=""):
        val = str(self.data.get(addr, default))
        if val.startswith("="):
            return str(self._eval_formula(val.strip()[1:]))
        return val


sheet = MySheet()

sheet.put("A1", "hello")
print("A1 should be hello:", sheet.get("A1"))

sheet.put("B2", "5")
print("B2 should be 5:", sheet.get("B2"))

sheet.put("A3", "=2+2")
print("A3 should be 4", sheet.get("A3"))

sheet.put("C3", "=B2+2")
print("C3 should be 7:", sheet.get("C3"))

sheet.put("B2", "=10")
print("C3 should be 12", sheet.get("C3"))

sheet.put("B2", "=10+10")
print("C3 should be 22:", sheet.get("C3"))

# some edge-cases around formulas
sheet.put("D1", " = 5 + C3 + EZ88")
print("D1 should be 27", sheet.get("D1"))


def _test(sheet, addr, expected, annotation=""):
    val = sheet.get(addr)
    msg = f"{addr} should be {expected}, is {val} {annotation}"
    if val != expected:
        assert val == expected, msg
    else:
        print(f"[PASS] {msg}")


def test_part2_lazy():
    sheet = MySheet()

    sheet.put("A1", "hello")
    _test(sheet, "A1", "hello")

    sheet.put("B2", "5")
    _test(sheet, "B2", "5")

    sheet.put("A3", "=2+2")
    _test(sheet, "A3", "4")

    sheet.put("C3", "=B2+2")
    _test(sheet, "C3", "7")

    sheet.put("B2", "=10")
    _test(sheet, "C3", "12", "updated formula reference")

    sheet.put("B2", "=10+10")
    _test(sheet, "C3", "22", "nested formulas")

    # some edge-cases around formulas
    sheet.put("D1", " = 5 + C3 + EZ88")
    _test(sheet, "D1", "27", "harder formula edge cases")


if __name__ == "__main__":
    test_part2_lazy()
