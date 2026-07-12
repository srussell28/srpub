def is_formula(v):
    return v.strip().startswith("=")


def eval_formula(v):
    r = v.strip().lstrip("=")
    terms = r.split("+")
    as_ints = [int(x) for x in terms]
    return sum(as_ints)


class MySheet:
    def __init__(self):
        self.data = {}

    def put(self, addr, value):
        if is_formula(value):
            value = eval_formula(value)
        self.data[addr] = value

    def get(self, addr):
        return self.data.get(addr, "")


sheet = MySheet()

sheet.put("A1", "hello")
print("A1", sheet.get("A1"))

sheet.put("B2", "5")
print("B2", sheet.get("B2"))

sheet.put("A3", "=2+2")
print("A3", sheet.get("A3"))
