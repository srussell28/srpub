"""
This solution is more complicated, but efficient
because it will not re-do computation on get calls
"""

from dataclasses import dataclass, field


class CycleError(Exception):
    pass


@dataclass
class Cell:
    raw: str | None = None
    value: str | int | None = None

    # the addrs of all cells referencing this one
    dependents: set[str] = field(default_factory=set)

    # the addrs this cell's formula references,
    # so we can drop stale edges when its replaced
    references: set[str] = field(default_factory=set)


def is_formula(v):
    return v.strip().startswith("=")


def is_number(v):
    try:
        int(v)
        return True
    except (ValueError, TypeError):
        return False


class MySheet:
    def __init__(self):
        self.data = {}

    def _eval_formula(self, cell, addr, v):
        r = v.strip().lstrip("=")
        terms = [x.strip() for x in r.split("+")]
        s = 0
        for x in terms:
            if is_number(x):
                s += int(x)
            else:
                # if its not a number, it must be a cell-addr
                other = self.data.get(x)
                # if referenced cell doesnt exit, create it
                if not other:
                    other = Cell()
                    self.data[x] = other
                # Put this cell as a dependent of the other
                if other:
                    s += other.value or 0
                    other.dependents.add(addr)
                    cell.references.add(x)

        return s

    def _update(self, addr, value=None, loop_orig=None):
        if not loop_orig:
            # this is the first update, mark ourself as the start of the loop
            loop_orig = addr
        else:
            if addr == loop_orig:
                raise CycleError(f"cycle detected at {addr}")

        # get existing cell, or create one
        c = self.data.get(addr, Cell())
        if value is not None:
            # the raw changed, drop the old dependency edges so a
            # replaced formula can't leave phantom cycles behind
            for ref in c.references:
                self.data[ref].dependents.discard(addr)
            c.references = set()
            c.raw = value

        # put value from the raw
        if is_number(c.raw):
            c.value = int(c.raw)
        elif is_formula(c.raw):
            c.value = self._eval_formula(c, addr, c.raw)
        else:
            c.value = str(c.raw)

        # update dependents
        for dep in c.dependents:
            self._update(dep, loop_orig=loop_orig)

        self.data[addr] = c

    def put(self, addr, value):
        # get existing cell, or create one
        self._update(addr, value=value)

    def get(self, addr):
        c = self.data.get(addr)
        return c.value if c else ""


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

print("\nhard mode, refernces to not-yet-existent cells")
sheet.put("F4", "=F5+2")
print("F4 should be 2:", sheet.get("F4"))
sheet.put("F5", "3")
print("F4 should be 5:", sheet.get("F4"))

print("\nhard mode, unusual spacing, high addresses")
sheet.put("ZZZZDF22222", "3")
sheet.put("ZZZZB12312", " =        ZZZZDF22222  +    2")
print("ZZZZB12312 should be 5:", sheet.get("ZZZZB12312"))

print("\nhard mode, branching, merging, double references")
sheet.put("K1", "2")
sheet.put("K2", "=K1+K1+2")
sheet.put("K3", "=K1+2")
sheet.put("K4", "=K2+K3+K1")
print("K4 should be 12:", sheet.get("K4"))
sheet.put("K1", "1")
print("K4 should be 8:", sheet.get("K4"))

print("\nhard mode, cycle detection")
sheet.put("Q1", "=Q2+2")
sheet.put("Q2", "=Q3+2")
did_error = False
try:
    sheet.put("Q3", "=Q1+2")
except CycleError as e:
    did_error = True
    print(f"Did correctly error: {e}")
if not did_error:
    print("Should have errored for cycle, but did not")

print("\nhard mode, replacing a formula drops the old reference")
sheet.put("R1", "1")
sheet.put("R2", "=R1+1")
sheet.put("R2", "5")
sheet.put("R1", "=R2")  # R2 no longer references R1, so not a cycle
print("R1 should be 5:", sheet.get("R1"))
