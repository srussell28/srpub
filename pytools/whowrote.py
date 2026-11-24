#!/usr/bin/env python3

import argparse
import operator
import re
from collections.abc import Iterator
from pathlib import Path

from srutils import GitNameMatcher, cmd


def title_from_sha(sha):
    res = cmd("git show " + sha)
    try:
        res = res.split("\n")[4]
    except Exception:
        res = ""
    return res


IGNORE_PATTERNS = {".env", "__pycache__", "pyc", "build"}

name_matcher = GitNameMatcher()


def should_ignore(path: Path) -> bool:
    return any(pattern in path.parts for pattern in IGNORE_PATTERNS)


def args_to_files(paths) -> Iterator[Path]:
    """
    Generate Path objects for all Python files from provided paths.
    Recursively processes directories and includes direct file arguments.

    Args:
        paths: List of file or directory paths

    Returns:
        Iterator of Path objects for Python files
    """
    for arg in paths:
        path = Path(arg)
        if not path.exists():
            print(f"Path does not exist: {path}")
            continue

        if path.is_file():
            # Yield explicitly passed in paths
            yield path
        else:
            # For directorys default to python files
            yield from (p for p in path.rglob("*.py") if not should_ignore(p))


def main():
    parser = argparse.ArgumentParser(
        description="Analyze who wrote code in Python files"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Files or directories to analyze (default: current directory)",
    )

    args = parser.parse_args()

    cnts = dict()
    auths = dict()
    auth_lines = dict()
    auth_commits = dict()
    lc = 0
    unique_shas = set()

    all_files = list(args_to_files(args.paths))

    # First pass: collect all SHAs from blame
    for a in all_files:
        for line in cmd(f"git blame {a}").split("\n"):
            ls = re.split(r" |\(", line)
            if len(ls) < 4:
                continue
            sha = ls[0].replace("^", "").strip()
            if sha:
                unique_shas.add(sha)

    # Populate name matcher with name+email from just the SHAs we found
    for sha in unique_shas:
        info = cmd(f"git show -s --format='%aN|%aE' {sha}")
        if "|" in info:
            name, email = info.rsplit("|", 1)
            name = name.strip()
            email = email.strip().lower()
            name_matcher.put_in_known(name, email)

    # Second pass: process blame with canonical names
    for a in all_files:
        for line in cmd(f"git blame -e {a}").split("\n"):
            m = re.search(r"\((.*?)\)", line)
            if m:
                email = " ".join(m.group(1).split()[0:-4]).strip("<>").lower()
                auth = (
                    name_matcher.get_name(email)
                    if email in name_matcher.kauths
                    else email
                )
            else:
                print(f"failed: {line}")
                continue

            ls = re.split(r" |\(", line)
            if len(ls) < 4:
                continue
            sha = ls[0].replace("^", "")
            auths[sha] = auth
            lc += 1
            if sha in cnts:
                cnts[sha] += 1
            else:
                cnts[sha] = 0
                if auth in auth_commits:
                    auth_commits[auth] += 1
                else:
                    auth_commits[auth] = 0
            if auth in auth_lines:
                auth_lines[auth] += 1
            else:
                auth_lines[auth] = 0

    sorted_cnts = sorted(cnts.items(), key=operator.itemgetter(1))
    sorted_cnts.reverse()
    for sha, cnt in sorted_cnts:
        author = name_matcher.get_bestname(auths[sha])
        print(
            f"{sha}\t{cnt}\t{int(100.0 * float(cnt) / lc)}%\t{author:20}\t{title_from_sha(sha)}"
        )

    # Print the original author, by file
    print("\n---- Original File Creator -----\n")
    for a in all_files:
        auth = None
        for line in cmd(f"git log --format=short {a}").split("\n"):
            m = re.search(r"Author\:(.*?)$", line)
            if m:
                auth = m.group(1)
            else:
                continue
        print(f"{auth:50}", a)

    # Print the aggregated git-blame coverage
    print("\n---- Current Git-Blame Modifier -----\n")
    print(f"{'author':20}\tlines\tperc\tcommits")
    print(f"{'------':20}\t-----\t----\t-------")
    sorted_auth_lines = sorted(auth_lines.items(), key=operator.itemgetter(1))
    sorted_auth_lines.reverse()
    for auth, cnt in sorted_auth_lines:
        author = name_matcher.get_bestname(auth)
        print(
            f"{author:20}\t{cnt}\t{int(100.0 * float(cnt) / lc)}%\t{auth_commits[auth]}"
        )


if __name__ == "__main__":
    main()
