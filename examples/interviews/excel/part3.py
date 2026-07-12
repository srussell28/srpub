from threading import Lock

from flask import Flask, request

app = Flask(__name__)

# flask serves requests on multiple threads, so a single in-process
# lock is enough here.  With multiple worker processes (gunicorn etc)
# both this lock and the in-memory dict break, and we'd need to move
# the data to a real shared datastore.
lock = Lock()


class MySheet:
    def __init__(self):
        self.data = {}

    def put(self, addr, value):
        lock.acquire()
        try:
            if is_formula(value):
                value = eval_formula(value)
            self.data[addr] = value
        finally:
            lock.release()

    def get(self, addr):
        # single dict reads are atomic in cpython, no lock needed
        return self.data.get(addr, "")


sheet = MySheet()


def is_formula(v):
    return v.strip().startswith("=")


def eval_formula(v):
    r = v.strip().lstrip("=")
    terms = r.split("+")
    as_ints = [int(x) for x in terms]
    return sum(as_ints)


@app.route("/cell/<addr>", methods=["GET"])
def get(addr):
    return str(sheet.get(addr))


@app.route("/cell/<addr>", methods=["PUT"])
def put(addr):
    content = request.get_json()
    if not content:
        return "request body required", 400
    value = content.get("value", None)
    if not value:
        return "value required", 400
    sheet.put(addr, value)
    return "ok"


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port="5050")


# curl -XPUT -H "Content-Type:application/json" "127.0.01:5050/cell/A1" --data '{"value": "hello"}'
# curl -XGET  -H "Content-Type:application/json" "127.0.01:5050/cell/A1" -H "Content-Type:application/json"

# curl -XPUT -H "Content-Type:application/json" "127.0.01:5050/cell/B2" --data '{"value": "5"}'
# curl -XGET  -H "Content-Type:application/json" "127.0.01:5050/cell/B2" -H "Content-Type:application/json"

# curl -XPUT -H "Content-Type:application/json" "127.0.01:5050/cell/A3" --data '{"value": "=2+2"}'
# curl -XGET  -H "Content-Type:application/json" "127.0.01:5050/cell/A3" -H "Content-Type:application/json"
