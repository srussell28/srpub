#!/usr/bin/env python3


import datetime
import shutil
import math
import os
import re
import shlex
import subprocess
import sys
import time
import codecs
import json
import logging

from colorstrings import yellow_str, red_str


os_name = os.name
is_windows = sys.platform.lower().startswith("win")
basedir, _ = os.path.split(__file__)


my_email = codecs.decode(b"737232323838323240676d61696c2e636f6d", "hex").decode()
name_aliases = ["Samuel Russell", "Sam Russell"]

if __name__ == "__main__":
    print("nope")


def ash(c, wait=True, noisy=False):
    fullcmd = 'adb shell "' + c + '"'
    return cmd(fullcmd, wait=wait, noisy=noisy)


def getprop(prop):
    return ash("getprop " + prop, wait=True, noisy=False)


def adb_available():
    res = cmd("adb get-state")
    return "device" in res.lower()


def utc_seconds():
    import calendar

    return calendar.timegm(time.gmtime())


def noisy_sleep(duration, tag=""):
    start = datetime.datetime.now()
    while True:
        time.sleep(1)
        left = duration - seconds_between(start, datetime.datetime.now())
        if left <= 0:
            break
        hrs = int(left / 3600)
        mins = int((left / 60) % 60)
        secs = left % 60
        flushprint(f"{tag} {int(hrs):02}:{int(mins):02}:{int(secs):02}")
        if int(secs) % 10 == 0:
            try:
                import alice

                if alice.alice_enabled():
                    alice.alice_check_status()
            except Exception:
                pass
    flushprint("                                                ")
    print("")


def term_width(buffer=3):
    return int(shutil.get_terminal_size().columns) - buffer


def fill_line(line, width=None):
    width = width or term_width()
    fill_amt = max(0, width - len(line))
    return line + " " * fill_amt


def flushprint(content):
    width = term_width()
    if type(content) is str:
        sys.stdout.write("\r" + fill_line(content, width))
        sys.stdout.flush()
    elif type(content) is list:
        # Use \033[K (erase-to-EOL) per line so clearing is correct even when
        # lines contain ANSI codes (which inflate len() without adding visible width).
        out = "\r"
        for line in content[:-1]:
            out += line + "\033[K\n"
        out += content[-1] + "\033[K"
        out += f"\033[{len(content) - 1}A\r"
        sys.stdout.write(out)
        sys.stdout.flush()
    else:
        print(content)


def flushprint_to_stderr(line, nobuffer=False):
    if nobuffer:
        sys.stderr.write("\r" + str(line))
    else:
        sys.stderr.write("\r" + fill_line(line))
    sys.stderr.flush()


def status_bar(done, total, width=40):
    perc = int(width * float(done) / float(total))
    flushprint("[" + "|" * perc + " " * (width - perc) + "]")


def print_to_stderr(p):
    sys.stderr.write(p + "\n")


def in_tmux():
    # r = cmd('echo $TERM')
    r = cmd("echo $TMUX")
    return r != ""


def quick_ingest_line():
    while True:
        line = sys.stdin.readline()
        if not line:
            return
        yield line


def is_uuid(s):
    import uuid

    try:
        uuid.UUID(s)
        return True
    except Exception:
        return False


def is_email(s):
    return "@" in s


def argpop(argv, item):
    if item in argv:
        argv.remove(item)
        return True
    return False


def str_hash(obj):
    import hashlib

    print("Hashing", obj)
    if type(obj) is list:
        strv = "-".join([str(x) for x in sorted(obj)])
    else:
        strv = str(obj)
    print("strv is ", strv, type(strv))

    return hashlib.sha1(bytes(strv, "utf-8")).hexdigest()[-10:]


def yes_or_no(question):
    """Prompt for yes-no input, and parse into bool True-False"""
    while True:
        reply = str(input(question + "  [y/n]: ")).lower().strip()
        if not reply:
            continue
        if reply[0] == "y":
            return True
        if reply[0] == "n":
            return False


def confirm_or_exception(warning=None):
    """Given a warning, prompt the user if they'd like to proceed or exit"""
    print()
    msg = f"{warning}.  " if warning else ""
    msg += "Do you wish to proceed?"
    proceed = yes_or_no(msg)
    if not proceed:
        raise Exception(warning or "Aborted by user")


#################################################################
# Simple logging infra
#################################################################
_verbose = False


def set_verbose(v):
    global _verbose
    _verbose = v


def vprint(txt):
    if _verbose:
        print(f"[{now_str()}] {txt}")


def str_to_bool(value):
    return value.lower() in ("true", "t", "yes", "y", "1")


plain = str_to_bool(os.getenv("SR_LOGS_PLAIN", "False"))
verbose = str_to_bool(os.getenv("SR_LOGS_VERBOSE", "False"))

plain_format = "%(message)s"
verbose_format = "[%(asctime)s]-[%(levelname)s] %(message)s"
log_format = plain_format if plain else verbose_format

logging.basicConfig(format=log_format, level=logging.DEBUG if verbose else logging.INFO)
log = logging.getLogger()

#################################################################
# Simple file based cache
#################################################################


class DiskCache:
    def __init__(self, cache_name=None, verbose=False):
        self.verbose = verbose

        self.cache_name = cache_name or "global"
        cachedir = os.path.join(basedir, ".caches")
        os.makedirs(cachedir, exist_ok=True)
        self.cachef = os.path.join(cachedir, cache_name)
        self.vprint(f"[DiskCache {cache_name}] Initializing cache  at {self.cachef}")

        self._cache = {}
        if os.path.isfile(self.cachef):
            try:
                with open(self.cachef, "r") as f:
                    self._cache = json.loads(f.read())
            except (ValueError, OSError) as e:
                # A truncated/corrupt cache (e.g. from an interrupted or
                # concurrent write) must not crash the caller. Discard it;
                # the next set() rewrites a clean file.
                self.vprint(f"[DiskCache {cache_name}] ignoring bad cache: {e}")
                self._cache = {}

    def vprint(self, txt):
        if self.verbose:
            print(txt)

    def get(self, k, default=None):
        v = self._cache.get(k, default)
        self.vprint(f"[DiskCache {self.cache_name}] get {k} val {v}")
        return v

    def set(self, k, v):
        self.vprint(f"[DiskCache {self.cache_name}] get {k} val {v}")
        self._cache[k] = v
        # Write atomically (tmp file + rename) so an interrupted or concurrent
        # write can never leave a half-written, corrupt cache behind.
        self.vprint(f"writing {self.cache_name} to disk")
        tmpf = f"{self.cachef}.{os.getpid()}.tmp"
        try:
            with open(tmpf, "w") as f:
                f.write(json.dumps(self._cache))
            os.replace(tmpf, self.cachef)
        finally:
            if os.path.exists(tmpf):
                os.remove(tmpf)


#################################################################
# Pickling to/from files
#################################################################
def load_pickle(fname, default=None):
    import pickle

    try:
        with open(fname, "rb") as f:
            result = pickle.load(f)
    except IOError:
        if default is not None:
            return default
        raise
    return result


def save_pickle(obj, fname):
    import pickle

    with open(fname, "wb") as f:
        pickle.dump(obj, f)


#################################################################
# Time
#################################################################


def date_to_str(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def str_to_date(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")


def get_now():
    return datetime.datetime.now()


def now_str():
    return date_to_str(get_now())


def seconds_between(da, db):
    return (db - da).total_seconds()


def hours_between(da, db):
    return seconds_between(da, db) / 3600


def parse_duration(txt):
    """Parses the text as a duration, returned in int seconds"""
    duration = str(txt)
    if "mo" in duration:  # months
        duration = re.sub("mo", "", duration)
        duration = 30 * 24 * 60 * 60 * float(duration)
    elif "m" in duration:  # minutes
        duration = re.sub("m", "", duration)
        duration = 60 * float(duration)
    elif "h" in duration:  # hours
        duration = re.sub("h", "", duration)
        duration = 60 * 60 * float(duration)
    elif "d" in duration:  # days
        duration = re.sub("d", "", duration)
        duration = 24 * 60 * 60 * float(duration)
    elif "y" in duration:  # years
        duration = re.sub("y", "", duration)
        duration = 365 * 24 * 60 * 60 * float(duration)
    else:
        duration = re.sub("s", "", duration)
        duration = int(duration)
    return duration


def dur_to_human(secs):
    res = []
    years = int(secs / 31536000)
    if years > 0:
        secs -= years * 31536000
        res.append(str(years) + "-years")
        if years >= 2 or len(res) >= 2:
            return ":".join(res)
    days = int(secs / 86400)
    if days > 0:
        secs -= days * 86400
        res.append(str(days) + "-days")
        if days >= 2 or len(res) >= 2:
            return ":".join(res)
    hrs = int(secs / 3600)
    if hrs:
        secs -= hrs * 3600
        res.append(str(hrs) + "-hrs")
        if hrs >= 2 or len(res) >= 2:
            return ":".join(res)
    mins = int(secs / 60)
    if mins > 0:
        res.append(str(mins) + "-min")
        if mins >= 2 or len(res) >= 2:
            return ":".join(res)
    secs = secs % 60
    res.append(str(secs) + "-secs")
    return ":".join(res)


#################################################################
# Coloring
#################################################################


def termcode(num):
    # womp windows
    # if os_name == 'nt':
    #    return ''
    return f"\x1b[{num}m"


def print_error(s, fatal=False):
    print(red_str("\n[ERROR] " + s + "\n"))
    if fatal:
        sys.exit(1)


def print_warning(s):
    print(yellow_str("\n[WARNING] " + s + "\n"))


#################################################################
# HTML
#################################################################
table_style = """
<style>
    table.simple_table a:link {
        color: #666;
        font-weight: bold;
        text-decoration:none;
    }

    table.simple_table {
        font-family:Arial, Helvetica, sans-serif;
        color:#666;
        font-size:14px;
        text-shadow: 1px 1px 0px #fff;
        background:#eaebec;
        margin:auto;
        border:#ccc 1px solid;

        -moz-border-radius:3px;
        -webkit-border-radius:3px;
        border-radius:3px;

        -moz-box-shadow: 0 1px 2px #d1d1d1;
        -webkit-box-shadow: 0 1px 2px #d1d1d1;
        box-shadow: 0 1px 2px #d1d1d1;
    }
    table.simple_table th {
        padding:21px 25px 22px 25px;
        border-top:1px solid #fafafa;
        border-bottom:1px solid #e0e0e0;

        background: #ededed;
        background: -webkit-gradient(linear, left top, left bottom, from(#ededed), to(#ebebeb));
        background: -moz-linear-gradient(top,  #ededed,  #ebebeb);
    }
    table.simple_table tr {
        text-align: center;
        padding-left:20px;
    }
    table.simple_table td {
        padding:18px;
        border-top: 1px solid #ffffff;
        border-bottom:1px solid #e0e0e0;
        border-left: 1px solid #e0e0e0;

        background: #fafafa;
        background: -webkit-gradient(linear, left top, left bottom, from(#fbfbfb), to(#fafafa));
        background: -moz-linear-gradient(top,  #fbfbfb,  #fafafa);
    }
</style>
"""


def html_table(table):
    resp = ""
    resp += table_style
    resp += '<table class="simple_table">\n'
    for row in table:
        resp += "  <tr>\n"
        for col in row:
            resp += f"    <td>{col}</td>\n"
        resp += "  </tr>\n"
    resp += "</table>\n"
    return resp


def html_link(txt, link):
    return f'<a href="{link}">{txt}</a>'


#################################################################
# OS, Terminal, and Environment
#################################################################


def _needs_shell(c):
    """Check if a command string requires shell interpretation."""
    return any(ch in c for ch in "|&;<>$`")


def cmd(c, wait=True, noisy=False, straight_through=False):
    vprint(f"cmd: {c}")
    use_shell = _needs_shell(c)
    args = c if use_shell else shlex.split(c)

    if straight_through:
        process = subprocess.Popen(args, shell=use_shell)
        process.communicate()
        return ""

    if not wait:
        subprocess.Popen(
            args,
            shell=use_shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        return

    if noisy:
        process = subprocess.Popen(
            args,
            shell=use_shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        output = ""
        while True:
            nextline = process.stdout.readline()
            if nextline == "" and process.poll() is not None:
                break
            output += nextline
            sys.stdout.write(nextline)
            sys.stdout.flush()
        return output.rstrip()
    else:
        process = subprocess.Popen(
            args,
            shell=use_shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        output = process.communicate()[0]
        return output.rstrip()


def get_term_size():
    size = shutil.get_terminal_size(fallback=(160, 80))
    return size.lines, size.columns


def env_metadata():
    import getpass
    import socket

    return {
        "hostname": socket.gethostname(),
        "time": str(datetime.datetime.now()),
        "user": getpass.getuser(),
    }


#################################################################
# math
#################################################################


def average(lst):
    if not lst or len(lst) == 0:
        return 0.0
    return sum(lst) / len(lst)


def stddev(lst):
    avg = average(lst)
    var = map(lambda x: (x - avg) ** 2, lst)
    res = math.sqrt(average(var))
    return res


def median(lst):
    import numpy

    return numpy.median(numpy.array(lst)) if lst else 0


def p95(lst):
    import numpy

    return numpy.percentile(numpy.array(lst), 95) if lst else 0


def percentile(lst, n):
    """Return the n-th percentile of the list"""
    import numpy

    return numpy.percentile(numpy.array(lst), n) if lst else 0


def distance_between(lat1, long1, lat2, long2):
    """Return the distance between 2 lat/lng pairs in km"""

    # Convert latitude and longitude to
    # spherical coordinates in radians.
    degrees_to_radians = math.pi / 180.0

    # phi = 90 - latitude
    phi1 = (90.0 - lat1) * degrees_to_radians
    phi2 = (90.0 - lat2) * degrees_to_radians

    # theta = longitude
    theta1 = long1 * degrees_to_radians
    theta2 = long2 * degrees_to_radians

    # Compute spherical distance from spherical coordinates.
    # For two locations in spherical coordinates
    # (1, theta, phi) and (1, theta, phi)
    # cosine( arc length ) =
    #    sin phi sin phi' cos(theta-theta') + cos phi cos phi'
    # distance = rho * arc length

    cos = math.sin(phi1) * math.sin(phi2) * math.cos(theta1 - theta2) + math.cos(
        phi1
    ) * math.cos(phi2)

    try:
        arc = math.acos(cos)
    except Exception:
        # a bad acos means we are at 0 dist i think
        return 0.0

    # Remember to multiply arc by the radius of the earth
    # in your favorite set of units to get length.
    # 6371 is the radius in KM
    return arc * 6371


def to_metric_base(size_str):
    # Longer suffixes first so "Gi" matches before "G", etc.
    units = [
        ("Pi", 1024**5),
        ("Ti", 1024**4),
        ("Gi", 1024**3),
        ("Mi", 1024**2),
        ("Ki", 1024),
        ("Bi", 1),
        ("P", 1024**5),
        ("T", 1024**4),
        ("G", 1024**3),
        ("M", 1024**2),
        ("K", 1024),
        ("B", 1),
    ]
    size = size_str.strip()
    for unit, multiplier in units:
        if size.endswith(unit):
            try:
                return int(float(size[: -len(unit)]) * multiplier)
            except ValueError:
                raise ValueError(f"Invalid number format: {size}")
    raise ValueError(
        f"Unknown unit in: {size_str}. Expected one of: {', '.join(u for u, _ in units)}"
    )


def size_to_human(size_bytes):
    """Convert size in bytes to human-readable string with appropriate unit suffix."""
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(size_bytes)
    unit_index = 0
    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1
    return f"{size:.2f} {units[unit_index]}"


#################################################################
# Multiprocessing stuff
#################################################################


def get_config_int(cname, default=0):
    try:
        f = open(cname).read().strip()
        r = int(f)
        return r
    except Exception:
        return default


#################################################################
# AWS stuff
#################################################################

_boto_client_cache = {}


def cached_boto_client(x, region="us-east-1"):
    global _boto_client_cache
    import boto3

    if x in _boto_client_cache:
        return _boto_client_cache[x]
    c = boto3.client(x, region_name=region)
    _boto_client_cache[x] = c
    return c


def send_email(source, to, subject, body):
    # Requires IAM user
    identity = cached_boto_client("sts").get_caller_identity().get("Arn")
    assert identity.endswith("user/sam"), (
        f"Must sign in to IAM user to send SES email: {identity}"
    )
    client = cached_boto_client("ses")
    response = client.send_email(
        Source=source,
        Destination={
            "ToAddresses": [
                to,
            ],
            "CcAddresses": [],
            "BccAddresses": [],
        },
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Text": {"Data": body, "Charset": "UTF-8"},
                #'Html': {
                #    'Data': 'string',
                #    'Charset': 'UTF-8'
                # }
            },
        },
    )
    print(response)


#################################################################
# git stuff
#################################################################


def looks_similar(a, b):
    """Return true if string `a` looks pretty similar to `b`

    The algorithm basically comparse each coresponding word for
    case-insensitive substring matches
    """
    a = a.lower().strip()
    b = b.lower().strip()
    if a == b:
        return True
    words_a = a.split(" ")
    words_b = b.split(" ")
    if len(words_a) != len(words_b):
        # this is a little dubious, but if one is at least 8 characters
        # and appears entirely in the other, count that
        smoosh_a = "".join(words_a)
        smoosh_b = "".join(words_b)
        if len(smoosh_a) >= 8 and smoosh_a in smoosh_b:
            return True
        if len(smoosh_b) >= 8 and smoosh_b in smoosh_a:
            return True

        return False
    for idx in range(len(words_a)):
        if words_a[idx] in words_b[idx] or words_b[idx] in words_a[idx]:
            continue
        return False
    return True


class GitNameMatcher:
    def __init__(self):
        # A map of known aliases -> canonical key
        self.kauths = {}
        # A map of canonical key -> best display name
        self.bestname = {}

    def _name_score(self, name):
        """Score for choosing best display name (higher is better)"""
        score = len(name)
        if "@" not in name:  # Prefer non-emails
            score += 200
        if " " in name:  # Prefer "First Last" over "username"
            score += 100
        return score

    def _maybe_update_best(self, kname, newthing):
        score = self._name_score(newthing)
        if score > self._name_score(self.bestname.get(kname, "")):
            self.bestname[kname] = newthing

    def put_in_known(self, name, email):
        assert name
        assert email

        # if we have already seen both the name and email, no addition needed
        if name in self.kauths and email in self.kauths:
            return

        if name in self.kauths:
            # we have seen the name, but not the email
            kname = self.kauths[name]
            self.kauths[email] = kname
            self._maybe_update_best(kname, email)
            return

        if email in self.kauths:
            # we have seen the email, but not the name
            kname = self.kauths[email]
            self.kauths[name] = kname
            self._maybe_update_best(kname, name)
            return

        # we have seen neither the exact email nor exact name
        for other_auth in self.kauths.keys():
            if looks_similar(name, other_auth):
                kname = self.kauths[other_auth]

                self.kauths[name] = kname
                self.kauths[email] = kname
                self._maybe_update_best(kname, name)
                self._maybe_update_best(kname, email)
                return

        # we did not find any similar name matches
        # so add a new entry
        kname = name

        self.kauths[name] = kname
        self.kauths[email] = kname
        self._maybe_update_best(kname, name)
        self._maybe_update_best(kname, email)

    def get_name(self, name):
        kname = self.kauths[name]
        return kname

    def get_bestname(self, name):
        kname = self.kauths[name]
        return self.bestname[kname]

    def get_aliases(self, name, emails=True):
        res = {}
        for k, v in self.kauths.items():
            if v == name:
                if "@" in k or not emails:
                    res[k] = True
        return res.keys()
