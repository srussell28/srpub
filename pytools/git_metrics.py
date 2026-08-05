#!/usr/bin/env python3


import argparse
import datetime
import operator
import re
import time

from colorstrings import blue_str, grey_str
from srutils import (
    GitNameMatcher,
    cmd,
    dur_to_human,
    looks_similar,
    name_aliases,
    parse_duration,
)

MY_NAME = cmd("git config user.name") or name_aliases[0]

parser = argparse.ArgumentParser()
parser.add_argument(
    "--user", type=str, required=False, default=MY_NAME, help="The user to highlight."
)
parser.add_argument(
    "--period",
    type=str,
    required=False,
    help="The time-period to run-over, (e.g. 200 or 2y)",
)
parser.add_argument(
    "--num",
    type=int,
    required=False,
    default=10,
    help="The number of users to show per leaderboard",
)
parser.add_argument("--overall", action="store_true", help="Show overall")
parser.add_argument(
    "--only-prs", action="store_true", help="Only count PR commits in metrics"
)
parser.add_argument(
    "--all-parents",
    action="store_true",
    help="Include commits from all parents (default is --first-parent)",
)
parser.add_argument(
    "--loc",
    action="store_true",
    help="Count lines of code changed instead of commits/PRs",
)
parser.add_argument(
    "--order",
    action="store_true",
    help="List each unique author by date of first commit",
)
args = parser.parse_args()


def is_int(x):
    try:
        x = int(x)
        return True
    except ValueError:
        return False


def epoch_to_date(e):
    return datetime.datetime.fromtimestamp(e, datetime.timezone.utc).strftime(
        "%Y-%m-%d"
    )


def fmt_float(f, decimals=1, width=4):
    f_fmt = "%." + str(decimals) + "f"
    s_fmt = "%" + str(width) + "s"
    return s_fmt % (f_fmt % f)


class TimeRange:
    def __init__(self, start, end):
        self.start = start
        self.end = end

    def __str__(self):
        return f"[{epoch_to_date(self.start)} - {epoch_to_date(self.end)}]"

    def add(self, dt):
        self.start = min(self.start, dt)
        self.end = max(self.end, dt)

    def seconds(self):
        return self.end - self.start

    def weeks(self):
        return max(1, (self.seconds() / 604800))

    def human_dur(self):
        return dur_to_human(self.seconds())


class GitStat:
    def __init__(self):
        self.cnt = {}
        self.tim = TimeRange(9999999999, 0)

    def add(self, kname, dt, weight=1):
        self.cnt[kname] = self.cnt.get(kname, 0) + weight
        self.tim.add(dt)


# Set count and dur thresholds
thresh_cnt = 100
thresh_dur = "1y"
if args.period:
    if is_int(args.period):
        thresh_cnt = int(args.period)
    else:
        thresh_dur = args.period
thresh_dur_s = parse_duration(thresh_dur)

all_stat = GitStat()
since_me_stat = GitStat()
thresh_cnt_stat = GitStat()
thresh_dur_stat = GitStat()

user_active_tim = {}

name_matcher = GitNameMatcher()


def print_cnt_dict(title, stat, limit=args.num):
    sorted_x = sorted(stat.cnt.items(), key=operator.itemgetter(1), reverse=True)
    did_me = False
    total_cnt = sum(stat.cnt.values())
    description = "LOC" if args.loc else ("PRs" if args.only_prs else "commits")
    max_cnt = max(stat.cnt.values()) if stat.cnt else 0
    cw = max(5, len(f"{int(max_cnt)}"))
    max_rate = max_cnt / max(1, stat.tim.weeks())
    rw = max(5, len(f"{int(max_rate)}") + 2)
    print(
        f"\n\n=== {title} === \t ({stat.tim.human_dur()}) ({total_cnt} total {description};  {len(stat.cnt.keys())} unique authors)"
    )
    print(f"{'':3}   {'cnt':>{cw}} {'%':>4}  {'rate':>{rw}} name")
    print(f"{'':3}   {'---':>{cw}} {'---':>4}  {'----':>{rw}} ----")
    for i, x in enumerate(sorted_x):
        kname = x[0]
        is_me = looks_similar(kname, args.user)
        name = name_matcher.get_bestname(kname).title()
        if is_me:
            name = blue_str(name)
        cnt = x[1]
        rate = float(cnt) / stat.tim.weeks()
        if i == limit:
            if did_me:
                break
            else:
                print("                  ...")
        if i >= limit and not is_me:
            continue
        perc = int(100 * cnt / total_cnt)
        print(
            f"{int(i + 1):3}"
            + ". "
            + f"{int(cnt):>{cw}}  "
            + f"{int(perc):>3}%"
            + "  "
            + f"{rate:>{rw}.1f} "
            + name
        )
        if is_me:
            did_me = True


def find_main_branch():
    branches = cmd("git branch")
    branch_list = [
        line.strip().lstrip("* ") for line in branches.split("\n") if line.strip()
    ]

    for b in ["main", "master", "develop"]:
        if b in branch_list:
            return b
    return "master"


main_branch = find_main_branch()
git_log_format = "%H,%aN,%ae,%at,%s"
first_parent = "" if (args.all_parents and not args.only_prs) else "--first-parent"
git_log_raw = cmd(f"git log {main_branch} {first_parent} --format='{git_log_format}'")


def is_pr_commit(subject):
    """
    Determine if a commit is a PR commit based on its subject and body.
    Looks for patterns like "Merge pull request #9719" or "(#9687)" in the text.
    """
    if "Merge pull request #" in subject:
        return True
    return "(#" in subject and ")" in subject


loc_map = {}
if args.loc:
    loc_raw = cmd(f"git log {main_branch} {first_parent} --format='%H' --shortstat")
    current_sha = None
    for line in loc_raw.split("\n"):
        line = line.strip()
        if len(line) == 40 and all(c in "0123456789abcdef" for c in line):
            current_sha = line
        elif current_sha and ("insertion" in line or "deletion" in line):
            ins = re.search(r"(\d+) insertion", line)
            dels = re.search(r"(\d+) deletion", line)
            loc_map[current_sha] = (int(ins.group(1)) if ins else 0) + (
                int(dels.group(1)) if dels else 0
            )
            current_sha = None

dt_now = int(time.time())
seen_me = False
commits = git_log_raw.split("\n")

# Track PR commits to avoid counting them multiple times
processed_pr_commits = {}


for i, c in enumerate(reversed(commits)):
    cs = c.strip().split(",")
    if len(cs) < 5:
        continue
    sha = cs[0].strip()
    name = cs[1].strip().lower()

    # ewww, some names have commas in them
    if "@" not in cs[2] and "@" in cs[3]:
        name = name + " " + cs[2].strip().lower()
        cs.pop(2)

    email = cs[2].strip().lower()
    try:
        dt = int(cs[3].strip())
    except ValueError:
        print(f"Bad commit: {c}, skipping")
        continue
    subj = ",".join(cs[4:])

    # Skip merge commits unless counting PRs or using --first-parent
    if not args.only_prs and not first_parent and subj.startswith("Merge "):
        continue

    # Skip revert commits
    if subj.startswith("Revert"):
        continue

    # Check if this is a PR commit
    is_pr = is_pr_commit(subj)
    pr_number = None

    if is_pr:
        # Extract the PR number
        pr_match = None
        if "(#" in subj and ")" in subj:
            pr_match = re.search(r"\(#(\d+)\)", subj) or re.search(r"#\d{2,}", subj)
        elif "Merge pull request #" in subj:
            pr_match = re.search(r"Merge pull request #(\d+)", subj)

        if pr_match:
            pr_number = pr_match.group(1)
            if pr_number in processed_pr_commits:
                continue
            processed_pr_commits[pr_number] = True

    # Skip non-PR commits if --only-prs is specified
    if args.only_prs and not is_pr:
        continue

    is_mine = looks_similar(name, args.user)
    if is_mine:
        seen_me = True

    name_matcher.put_in_known(name, email)
    kname = name_matcher.get_name(name)

    # Add this commit to stat-counters it matches
    weight = loc_map.get(sha, 1) if args.loc else 1
    all_stat.add(kname, dt, weight)
    if seen_me:
        since_me_stat.add(kname, dt, weight)
    if (dt_now - dt) < thresh_dur_s:
        thresh_dur_stat.add(kname, dt, weight)
    if i > len(commits) - thresh_cnt:
        thresh_cnt_stat.add(kname, dt, weight)

    # Track each users "active contribution range"
    if kname not in user_active_tim:
        user_active_tim[kname] = TimeRange(dt, dt)
    user_active_tim[kname].add(dt)

# calculate each users rate-while-active
rate_while_active = {}
for key, tim in user_active_tim.items():
    cnt = all_stat.cnt[key]
    rate_while_active[key] = float(cnt) / tim.weeks()  # weekly rate

sorted_x = sorted(rate_while_active.items(), key=operator.itemgetter(1), reverse=True)


def print_active_rate():
    max_cnt = max(all_stat.cnt.values()) if all_stat.cnt else 0
    cw = max(5, len(f"{int(max_cnt)}"))
    max_rate = max((v for v in rate_while_active.values()), default=0)
    rw = max(4, len(f"{int(max_rate)}") + 2)
    print("\n\n=== Rate while active === \t")
    print(f"{'':3}  {'cnt':>{cw}} weeks {'rate':>{rw}}  name")
    print(f"{'':3}  {'---':>{cw}} ----- {'----':>{rw}}  ----")
    limit = args.num
    did_me = False
    for i, x in enumerate(sorted_x):
        kname = x[0]
        cnt = all_stat.cnt[kname]
        weeks = user_active_tim[kname].weeks()
        if weeks <= 2:
            continue
        is_me = looks_similar(kname, args.user)
        name = name_matcher.get_bestname(kname).title()
        name = f" {name: <25}"
        if is_me:
            did_me = True
            name = blue_str(name)
        val = x[1]
        if i == limit:
            if did_me:
                break
            else:
                print("                  ...")
        if i >= limit and not is_me:
            continue
        print(
            f"{int(i + 1):3}"
            + ". "
            + f"{int(cnt):>{cw}}"
            + f" {int(weeks):5} "
            + fmt_float(val, width=rw)
            + "  "
            + name
            + str(user_active_tim[kname])
        )


def print_order():
    """Chronological timeline of each author's first commit, plus - for
    authors inactive more than 4 months - their last commit as its own
    grey entry in date order."""
    stale_s = 6 * 30 * 86400
    events = []  # (dt, kind, kname)
    for kname, tim in user_active_tim.items():
        events.append((tim.start, "first", kname))
        if (dt_now - tim.end) > stale_s:
            events.append((tim.end, "last", kname))
    events.sort(key=lambda e: e[0])
    print(f"\n=== Author timeline === \t ({len(user_active_tim)} unique authors)")
    n = 0
    for dt, kind, kname in events:
        name = name_matcher.get_bestname(kname).title()
        if kind == "first":
            n += 1
            if looks_similar(kname, args.user):
                name = blue_str(name)
            print(f"{n:3}. {epoch_to_date(dt)}  {name}")
        else:
            print(grey_str(f"   x {epoch_to_date(dt)}  {name} (last)"))


if args.order:
    print_order()
elif args.overall:
    print_cnt_dict("Overall", all_stat, limit=100)
elif args.period:
    if is_int(args.period):
        print_cnt_dict(f"Last {thresh_cnt}", thresh_cnt_stat)
    else:
        print_cnt_dict(f"Last {thresh_dur}", thresh_dur_stat)
else:
    print_active_rate()
    # print personalized
    print_cnt_dict("Overall", all_stat)
    print_cnt_dict(f"Since {args.user}'s First", since_me_stat)
    print_cnt_dict(f"Last {thresh_dur}", thresh_dur_stat)
    print_cnt_dict(f"Last {thresh_cnt}", thresh_cnt_stat)
