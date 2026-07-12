"""
This solution is more complicated, but efficient
because it will not re-do computation on get calls

Note it does not detect reference cycles,
see part2_hard_mode.py for that
"""

import re
from dataclasses import dataclass, field


@dataclass
class Cell:
    raw: str = None
    value: str = None
    dependents: set[str] = field(default_factory=set)


class MySheet:
    def __init__(self):
        self.data: dict[str, Cell] = {}

    def _eval_formula(self, addr, v) -> int:
        # Could use re.finditer("[^\+^ ^=]+", v) here for better
        # mem-efficiency than split
        terms = [t.strip() for t in v.lstrip("=").split("+")]

        s = 0
        for term in terms:
            if term.isnumeric():
                s += int(term)
            else:
                # if its not a number, it must be a cell-addr
                assert re.match(r"^[A-Z]+\d+$", term)
                ref_cell = self.data.get(term, None)

                # if the referenced cell doesnt exist yet, create an
                # empty placeholder so we still record the dependency
                if not ref_cell:
                    ref_cell = Cell()
                    self.data[term] = ref_cell

                # Put this cell as a dependent of the other
                if ref_cell.value:
                    s += int(ref_cell.value)
                ref_cell.dependents.add(addr)

        return s

    def _update(self, addr, value=None):
        # get existing cell, or create one
        c = self.data.get(addr, Cell())
        if value:
            c.raw = value

        # calculate/set value from the raw
        if c.raw.startswith("="):
            c.value = str(self._eval_formula(addr, c.raw))
        else:
            c.value = c.raw

        # propegate _update to dependents
        for dep in c.dependents:
            self._update(dep)

        self.data[addr] = c

    def put(self, addr, value):
        # get existing cell, or create one
        self._update(addr, value=value)

    def get(self, addr):
        c = self.data.get(addr, None)
        # empty placeholder cells have value None
        return c.value if c and c.value is not None else ""


def _test(sheet, addr, expected, annotation=""):
    val = sheet.get(addr)
    msg = f"{addr} should be {expected}, is {val} {annotation}"
    if val != expected:
        assert val == expected, msg
    else:
        print(f"[PASS] {msg}")


def test_part2():
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

    sheet.put("G1", "= B2 + 2")
    _test(sheet, "G1", "22", "spaces in formula")

    sheet.put("F4", "=F5+2")
    _test(sheet, "F4", "2", "reference to not-yet-set cell")
    sheet.put("F5", "3")
    _test(sheet, "F4", "5", "forward reference updated")


if __name__ == "__main__":
    test_part2()
