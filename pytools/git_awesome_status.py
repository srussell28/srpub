#!/usr/bin/env python3
import argparse
import concurrent.futures
import datetime
import re
import sys
from operator import itemgetter
from pathlib import Path

from srutils import (
    my_email,
    name_aliases,
    is_windows,
    get_term_size,
    cmd,
    yes_or_no,
    DiskCache,
    set_verbose,
)

from colorstrings import (
    blue_str,
    cyan_str,
    green_str,
    grey_str,
    magenta_str,
    red_str,
    bold_str,
)


###########################################################
#     Helper Classes & Data
###########################################################
class Commit:
    """Represents a single commit with a SHA and title."""

    def __init__(self, sha: str, title: str):
        self.sha = sha
        self.title = title


git_config_defaults = {
    "user.email": my_email,
    "user.name": name_aliases[0],
    "core.editor": "vim",
}


###########################################################
#     Helper Functions
###########################################################
def clean_up_decorate(lines: str) -> str:
    """
    Cleans up parentheses decorations from git log lines, removing tags related to deployments.
    """
    result_lines = []
    for line in lines.split("\n"):
        match = re.search(r"\((.+?)\)", line)
        if match:
            decorate = match.group(1)
            tags = [t.strip() for t in decorate.split(",")]
            filtered_tags = [
                t
                for t in tags
                if not t.startswith("deploy_build") and not t.startswith("deployed")
            ]
            if not filtered_tags:
                line = line.replace(f"({decorate})", "")
            else:
                line = line.replace(decorate, ", ".join(filtered_tags))
        result_lines.append(line)
    return "\n".join(result_lines) + "\n"


def check_config():
    """
    Check if global git config is set for user email, user name, etc.
    Only prompt to set defaults if this looks like Sam's machine; otherwise just warn.
    """
    import os

    is_sam = any(
        alias in (os.environ.get("USER", "") + os.environ.get("HOME", ""))
        for alias in name_aliases
        + ["sr228822", "samrussell", "samuel", "a.sam.russell", "srussell28"]
    )

    print("1st run checking git config:")
    for key, value in git_config_defaults.items():
        current_val = cmd(f"git config --global --get {key}")
        print(f"\tgit config {key} : {current_val}")
        if not current_val:
            if is_sam:
                if yes_or_no(
                    f"git config --global {key} not set! Set it to {value} now?"
                ):
                    cmd(f"git config --global {key} {value}")
            else:
                print(
                    f"\tWarning: git config {key} not set (skipping auto-set on non-Sam machine)"
                )


def git_op_colored(command: str) -> str:
    """
    Run a git command, clean up decorated lines, highlight aliases, and print the result.
    On Windows, run with straight_through once for colors, then return normal output.
    """
    if is_windows:
        cmd(command, straight_through=True)
        return cmd(command)

    raw = cmd(command)
    cleaned = clean_up_decorate(raw)
    for alias in name_aliases:
        cleaned = cleaned.replace(alias, blue_str(alias))
    print(cleaned)
    return cleaned


_COMMIT_FMT = '"%Cgreen%h%Creset  %as  %an %C(yellow)%d%Creset%n   %s%n"'
_COMMIT_FMT_PLAIN = '"%h  %as  %an%n   %s%n"'


def show_sha(sha: str):
    command = (
        f"git --no-pager log --color=always --pretty=format:{_COMMIT_FMT} -1 {sha}"
    )
    return git_op_colored(command)


def show_shas(sha_first: str, sha_last: str, nmax: int = 100) -> str:
    command = (
        f"git --no-pager log -n {nmax} --color=always "
        f"--pretty=format:{_COMMIT_FMT} {sha_first}...{sha_last}"
    )
    return git_op_colored(command)


def show_my_most_recent(fb: str):
    command = (
        f"git --no-pager log --color=always --author=Russell "
        f"--pretty=format:{_COMMIT_FMT} -1 {fb}"
    )
    return git_op_colored(command)


def show_sha_grey(sha: str):
    command = f"git --no-pager log --pretty=format:{_COMMIT_FMT_PLAIN} -1 {sha}"
    if is_windows:
        cmd(command, straight_through=True)
        return

    res = cmd(command)
    for alias in name_aliases:
        if alias in res:
            parts = res.split(alias)
            res = grey_str(parts[0]) + blue_str(alias) + grey_str(parts[1])
        else:
            res = grey_str(res)
    print(res)
    print("")


def show_sha_magenta(sha: str):
    command = (
        f"git --no-pager log --color=always --pretty=format:"
        f'"%C(magenta)%h%Creset  %as  %an %C(yellow)%d%Creset%n   %s%n" -1 {sha}'
    )
    return git_op_colored(command)


def branch_diff_stat(base_sha: str, tip_ref: str) -> str:
    """Return a compact '+N -M (K files)' string for the diff between base and tip."""
    raw = cmd(f"git diff --shortstat {base_sha}..{tip_ref}").strip()
    m_files = re.search(r"(\d+) file", raw)
    m_ins = re.search(r"(\d+) insertion", raw)
    m_del = re.search(r"(\d+) deletion", raw)
    if not m_files:
        return ""
    files = m_files.group(1)
    ins = m_ins.group(1) if m_ins else "0"
    dels = m_del.group(1) if m_del else "0"
    return f"+{ins} -{dels} ({files} {'file' if files == '1' else 'files'})"


def fetch_commits_for_branch(branch: str, n: int) -> list:
    """
    Fetch up to n commits (sha and title) for the given branch.
    If the branch doesn't exist or we're not in a repo, exit gracefully.
    """
    raw = cmd(f"git log {branch} --format=oneline -n {n}")
    if "not a git repository" in raw.lower():
        print(red_str("Not a git repository"))
        sys.exit(1)
    if "unknown revision or path not in the working tree" in raw:
        return []

    commits = []
    for line in raw.rstrip().split("\n"):
        if line.startswith("warning"):
            continue
        parts = line.split()
        sha = parts[0]
        title = " ".join(parts[1:])
        # Adjust title if it matches a known pattern
        if "These files were automatically checked in" in title:
            title = sha
        commits.append(Commit(sha, title))
    return commits


def fb_alternate() -> str:
    """
    Try to find a fallback remote branch if not directly known.
    """
    branches_raw = cmd("git branch -vv").rstrip()
    for branch_line in branches_raw.split("\n"):
        if branch_line.startswith("*"):
            # Try to extract something from brackets [remote/branch]
            match = re.search(r"\[(.*?)\]", branch_line)
            if match:
                return match.group(1)
            # Or HEAD detached scenario
            match = re.search(r"HEAD detached at (.+?)\)", branch_line)
            if match:
                return match.group(1)
    if "origin" in branches_raw:
        return "origin"
    return None


def get_branch_age(branch: str):
    """
    Return a tuple of (branch, datetime, age_str).
    """
    try:
        stats = (
            cmd(f'git log -n 1 --pretty=format:"%ci %cr" {branch} -- | head -n 1')
            .strip()
            .split(" ")
        )
        dt = datetime.datetime.strptime(stats[0] + " " + stats[1], "%Y-%m-%d %H:%M:%S")
        age = stats[3] + " " + stats[4] if len(stats) > 4 else ""
        age = age.replace(" weeks", "w")
        age = age.replace(" days", "d")
        age = age.replace(" months", "m")
        age = age.replace(" years", "y")
        age = age.replace(" year", "y")
    except Exception:
        dt = datetime.datetime.now()
        age = ""
    return branch, dt, age


def get_branch_remote_status(cache=None, ttl_seconds=300) -> dict:
    """
    Returns a dict mapping branch name to remote status (by name match, ignoring tracking):
    - 'local_only': no same-named remote branch
    - 'has_remote': same-named remote branch exists
    - 'gone': same-named remote was deleted (stale local ref exists)

    Results are cached to disk with a TTL (default 5 minutes).
    """
    cache_key = "branch_remote_status"
    if cache:
        cached = cache.get(cache_key)
        if cached:
            ts, data = cached.get("ts", 0), cached.get("data", {})
            if datetime.datetime.now().timestamp() - ts < ttl_seconds:
                return data

    # Get actual remote branches from server
    ls_remote = cmd("git ls-remote --heads origin 2>/dev/null").strip()
    actual_remote = set()
    for line in ls_remote.split("\n"):
        if line and "\t" in line:
            ref = line.split("\t")[1]
            if ref.startswith("refs/heads/"):
                actual_remote.add(ref[len("refs/heads/") :])

    # Get local remote-tracking refs (may be stale)
    stale_refs = set()
    for line in cmd("git branch -r 2>/dev/null").strip().split("\n"):
        line = line.strip()
        if line.startswith("origin/") and " -> " not in line:
            stale_refs.add(line[len("origin/") :])

    # Classify each local branch by same-named remote status
    status = {}
    for line in cmd("git branch").strip().split("\n"):
        branch = line.lstrip("* ").strip()
        if not branch:
            continue
        if branch in stale_refs and branch not in actual_remote:
            status[branch] = "gone"  # had remote, now deleted
        elif branch in actual_remote:
            status[branch] = "has_remote"
        else:
            status[branch] = "local_only"

    if cache:
        cache.set(
            cache_key, {"ts": datetime.datetime.now().timestamp(), "data": status}
        )

    return status


def color_branch_by_remote(branch: str, text: str, remote_status: dict) -> str:
    """Color text based on branch's remote status."""
    status = remote_status.get(branch, "local_only")
    if status == "gone":
        return red_str(text)
    elif status == "has_remote":
        return cyan_str(text)
    else:  # local_only
        return text  # white (default terminal color)


###########################################################
#     Main Logic
###########################################################
def main():
    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--archive", type=str, required=False, help="Archive the specified branch"
    )
    parser.add_argument("--main", action="store_true", help="Use origin/main as fb")
    parser.add_argument("--all", action="store_true", help="Show all missing commits")
    parser.add_argument("--verbose", action="store_true", help="Verbose debug logs")
    parser.add_argument(
        "--no-remote-status",
        action="store_true",
        help="Disable branch coloring by remote status",
    )
    parser.add_argument(
        "--branch",
        type=str,
        required=False,
        help="Show status as if this branch were checked out",
    )
    args = parser.parse_args()

    if args.verbose:
        set_verbose(True)

    showall = args.all
    rows, cols = get_term_size()
    root = Path(cmd("git rev-parse --show-toplevel").strip())
    repo_name = root.name

    # Initialize cache
    cache = DiskCache(f"git_status_{repo_name}", verbose=args.verbose)

    # Check git config if not done before
    if not cache.get("config_checked"):
        check_config()
        cache.set("config_checked", True)

    # Handle archive action
    archived_branches = cache.get("archived_branches", [])
    if args.archive:
        archived_branches.append(args.archive)
        cache.set("archived_branches", archived_branches)
        sys.exit(0)

    # Print a new line to help reset coloring on Windows
    print("")

    # Determine target ref: either --branch or current HEAD
    target_ref = args.branch if args.branch else "HEAD"

    status = cmd("git status -bs").rstrip().split("\n")
    if not status or not status[0]:
        print(red_str("Not a git repo"))
        sys.exit(1)

    if args.branch:
        current_branch = args.branch
        # Find tracking branch for the specified branch
        tracking = cmd(f"git config branch.{args.branch}.merge 2>/dev/null").strip()
        remote = cmd(f"git config branch.{args.branch}.remote 2>/dev/null").strip()
        if tracking and remote:
            fb = remote + "/" + tracking.replace("refs/heads/", "")
        else:
            fb = fb_alternate()
        # No working-tree status for non-current branch
        status = [status[0]]
    else:
        branchline = status[0] + " "
        match = re.search(r"\.\.\.(.*?) ", branchline)
        if match:
            fb = match.group(1)
            branchline = branchline.replace("...", " ")
            current_branch = branchline.split()[1]
        else:
            current_branch = branchline.split()[1]
            fb = fb_alternate()

    # Detect the main branch for later use
    origin_head = cmd("git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null").strip()
    if origin_head:
        origin_main = origin_head.replace("refs/remotes/", "")
    elif fb and fb.startswith("origin/"):
        origin_main = "origin/main"
    else:
        origin_main = current_branch

    if args.main:
        fb = origin_main

    # Use merge-base to efficiently find common ancestor
    if fb:
        merge_base = cmd(f"git merge-base {target_ref} {fb}").strip()
    else:
        merge_base = None

    # Early exit if merge-base fails (e.g., no common history)
    if fb and (not merge_base or "fatal" in merge_base.lower()):
        print(red_str("Unable to find common ancestor with remote"))
        tot = fetch_commits_for_branch(target_ref, 6)
        for c in tot[:6]:
            show_sha(c.sha)
        sys.exit(1)

    # Count commits efficiently
    commits_ahead_raw = cmd(f"git rev-list --count {fb}..{target_ref}").strip()
    commits_behind_raw = cmd(f"git rev-list --count {target_ref}..{fb}").strip()

    try:
        commits_ahead = int(commits_ahead_raw)
        commits_behind = int(commits_behind_raw)
    except ValueError:
        commits_ahead = 0
        commits_behind = 0

    # When not tracking main, compute "made" relative to origin/main
    # so our branch commits show above the separator
    main_merge_base = None
    if fb != origin_main:
        main_merge_base = cmd(f"git merge-base {target_ref} {origin_main}").strip()
        main_ahead_raw = cmd(
            f"git rev-list --count {origin_main}..{target_ref}"
        ).strip()
        try:
            main_ahead = int(main_ahead_raw)
        except ValueError:
            main_ahead = 0
        if main_ahead > 0:
            made = fetch_commits_for_branch(target_ref, min(main_ahead + 10, 50))
            made = made[:main_ahead]
        else:
            made = []
    else:
        if commits_ahead > 0:
            made = fetch_commits_for_branch(target_ref, min(commits_ahead + 10, 50))
            made = made[:commits_ahead]
        else:
            made = []

    # Get commits in fb not in current branch (missing)
    if commits_behind > 0:
        if commits_behind <= 100:
            # One ranged git log instead of a subprocess per commit
            missing = fetch_commits_for_branch(f"{target_ref}..{fb}", commits_behind)
        else:
            missing = []
    else:
        missing = []

    # Check for cherry-picked commits (same title, different sha)
    check_base = origin_main if fb != origin_main else fb
    if made:
        origin = fetch_commits_for_branch(check_base, min(commits_behind + 50, 200))
        originsha = [c.sha for c in origin]
        origintitle = [c.title for c in origin]
        made_merged = [
            c for c in made if (c.title in origintitle and c.sha not in originsha)
        ]
        made = [c for c in made if c.title not in origintitle]
    else:
        made_merged = []

    # Get common commits for display
    if fb != origin_main and main_merge_base:
        common = fetch_commits_for_branch(main_merge_base, 15)
    else:
        common = fetch_commits_for_branch(merge_base, 15)

    # Show branches
    all_branches = cmd("git branch").strip().split("\n")
    checked_out = None
    other_branches = []
    for line in all_branches:
        if line.startswith("*"):
            checked_out = line.lstrip("* ").strip()
        else:
            other_branches.append(line.strip())
    # Remove the --branch target from the list (shown at top)
    other_branches = [x for x in other_branches if x != current_branch]
    # When --branch, add the checked-out branch back (it was stripped by the * filter)
    if args.branch and checked_out and checked_out != current_branch:
        other_branches.append(checked_out)
    if args.all:
        archived_branches = []
    other_branches = [x for x in other_branches if x not in archived_branches]

    # Calculate column width based on longest branch name
    max_branch_len = max((len(b) for b in other_branches), default=20)
    max_branch_len = max(max_branch_len, len(current_branch), 20)  # at least 20
    age_width = 5  # space + 4 char age field (e.g., "7d", "2w")
    col_width = max_branch_len + age_width
    branch_cols = max(1, cols // col_width)
    # If only 1 col fits; otherwise cap at 3 columns
    branch_cols = min(3, branch_cols)

    # Compute branch diff stat for display in header
    if made or fb != origin_main:
        stat_base = (
            main_merge_base if fb != origin_main and main_merge_base else merge_base
        )
        diff_stat = branch_diff_stat(stat_base, target_ref) if stat_base else ""
    else:
        diff_stat = ""

    print()
    print("*" * (cols - 10))
    age_prefix = " " * 5  # match age column width
    if current_branch == "HEAD":
        print(age_prefix + magenta_str(bold_str("~~ HEAD detached ~~")))
    elif args.branch:
        branch_line = green_str(bold_str(current_branch))
        if diff_stat:
            branch_line += "  " + green_str(diff_stat)
        print(age_prefix + branch_line)
    else:
        branch_line = blue_str(bold_str(current_branch))
        if diff_stat:
            branch_line += "  " + grey_str(diff_stat)
        print(age_prefix + branch_line)

    # Get remote status if flag enabled
    remote_status = get_branch_remote_status(cache) if not args.no_remote_status else {}

    # Retrieve branch ages concurrently
    branch_data = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(get_branch_age, b) for b in other_branches]
        for future in concurrent.futures.as_completed(futures):
            branch_data.append(future.result())

    branch_data_sorted = sorted(branch_data, key=itemgetter(1), reverse=True)
    for idx, (branch, dt, age) in enumerate(branch_data_sorted):
        # If age is in hours/minutes, optionally skip showing it.
        if "seconds" in age or "minutes" in age or "hours" in age:
            age = ""
        # Pad before coloring so ANSI codes don't affect alignment
        padded_branch = f"%-{max_branch_len}s" % branch
        if args.branch and branch == checked_out:
            padded_branch = blue_str(padded_branch)
        elif not args.no_remote_status:
            padded_branch = color_branch_by_remote(branch, padded_branch, remote_status)
        print(grey_str("%4s" % age) + " " + padded_branch, end="")
        if (idx + 1) % branch_cols == 0 or idx == len(branch_data) - 1:
            print("")

    if archived_branches:
        print(grey_str(age_prefix + f"{len(archived_branches)} archived branches"))

    print("*" * (cols - 10))

    # Print local status diffs
    untracked = [line for line in status[1:] if "??" in line]
    tracked = [line for line in status[1:] if "??" not in line]
    for line in tracked:
        print(magenta_str(line))

    if len(untracked) > 3:
        print(red_str(f"{len(untracked)} Untracked files ??"))
    else:
        for u in untracked:
            print(red_str(u))
    print("")

    if fb is None:
        # No remote tracking — just show recent commits
        print(grey_str("    ·········· no remote ············"))
        tot = fetch_commits_for_branch(target_ref, 6)
        for c in tot[:6]:
            show_sha(c.sha)
        return

    shown_shas = set()
    done = 0
    cp_but_merged = 0

    if fb != origin_main:
        # Split made into unpushed (ahead of fb) and pushed (on fb but not main)
        unpushed_shas = set(cmd(f"git rev-list {fb}..{target_ref}").strip().split("\n"))
        made_unpushed = [c for c in made if c.sha in unpushed_shas]
        made_pushed = [c for c in made if c.sha not in unpushed_shas]

        # Unpushed commits above the fb separator
        for c in made_unpushed:
            done += 1
            shown_shas.add(c.sha)
            show_sha(c.sha)

        # fb separator, then pushed commits
        print(blue_str("    ********** " + fb + " ************"))

        for c in made_pushed:
            done += 1
            shown_shas.add(c.sha)
            show_sha(c.sha)
        for c in made_merged:
            done += 1
            cp_but_merged += 1
            shown_shas.add(c.sha)
            show_sha_magenta(c.sha)

        # Commits on main not yet rebased into fb
        main_behind_raw = cmd(
            f"git rev-list --count {target_ref}..{origin_main}"
        ).strip()
        try:
            main_behind = int(main_behind_raw)
        except ValueError:
            main_behind = 0
        print(grey_str("    ·········· " + origin_main + " ············"))
        if main_behind > 0:
            if main_behind > 5 and not showall:
                print(
                    grey_str(
                        "   " + str(main_behind) + " commits behind " + origin_main
                    )
                )
                done += 2
            else:
                main_shas = (
                    cmd(f"git rev-list {target_ref}..{origin_main}").strip().split("\n")
                )
                for sha in main_shas:
                    if sha:
                        shown_shas.add(sha)
                        show_sha_grey(sha)
                        done += 1
    else:
        # Tracking main: my commits -> main separator -> behind main -> common
        for c in made:
            done += 1
            shown_shas.add(c.sha)
            show_sha(c.sha)
        for c in made_merged:
            done += 1
            cp_but_merged += 1
            shown_shas.add(c.sha)
            show_sha_magenta(c.sha)

        if fb == "master":
            print(grey_str("    ********** " + fb + " ************"))
        else:
            print(blue_str("    ********** " + fb + " ************"))

        if commits_behind > 5 and not showall:
            print(grey_str("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%"))
            print(grey_str("   " + str(commits_behind) + " missing commits"))
            print(grey_str("%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%"))
            done += 2
        else:
            for c in missing:
                shown_shas.add(c.sha)
                show_sha_grey(c.sha)
                done += 1

    # Print merged commits
    left = min(max(1, 10 - done), len(common) - 1)
    if len(common) > 1:
        originz = show_shas(common[0].sha, common[left].sha, nmax=left)
    elif len(common) == 1:
        originz = show_sha(common[0].sha)
    else:
        originz = ""

    # Print last merged commit by me if not already shown
    if not any(alias in originz for alias in name_aliases):
        my_branch = origin_main if fb != origin_main else fb
        my_sha = cmd(
            f"git --no-pager log --author=Russell --format=%H -1 {my_branch}"
        ).strip()
        if my_sha and my_sha not in shown_shas:
            print(grey_str("    ··················································"))
            show_my_most_recent(my_branch)


if __name__ == "__main__":
    main()
