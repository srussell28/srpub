#!/usr/bin/env python3
"""Analyze disk usage and find space to reclaim.

Default run is READ-ONLY: shows disk overview, largest directories, large
stale directories, large files, and known-reclaimable targets (trash, caches,
docker, brew, ...) with a total. Nothing is deleted unless you pass --clean,
and even then each category is confirmed individually.

    diskfree                  # report only
    diskfree --clean          # report, then per-category y/n cleanup
    diskfree --all-users      # one-line summary per /Users|/home homedir
    sudo diskfree.py <home>   # full sizes for another user's homedir
    diskfree --refresh        # bust the scan cache (default TTL 12h)

Scans (du/find over the root) are slow, so results are cached to disk via
DiskCache with a TTL (measured ~12s uncached on a full $HOME, <0.1s cached);
use --refresh to force a rescan. Dotfiles/dot-dirs are included in all scans
(du/find don't skip hidden). node_modules deletion is left to you.

Deliberately a deterministic script rather than a Claude skill: the work is
cache-friendly and identical on mac/ubuntu; a skill wrapper could add
"is this safe to delete?" judgment on top later.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from colorstrings import blue_str, bold_str, green_str, grey_str, red_str, yellow_str
from srutils import DiskCache, cmd, size_to_human, yes_or_no

is_mac = sys.platform == "darwin"
HOME = Path.home()
CACHE_TTL = 12 * 3600  # seconds


def hsize(kb):
    return size_to_human(kb * 1024)


def run_lines(args_list, timeout=600):
    """Run a command (no shell), return stdout lines; stderr discarded."""
    try:
        out = subprocess.run(
            args_list,
            capture_output=True,
            text=True,
            timeout=timeout,
        ).stdout
        return [ln for ln in out.split("\n") if ln]
    except (OSError, subprocess.TimeoutExpired):
        return []


def cached(cache, key, fn, refresh=False, ttl=CACHE_TTL):
    """Return fn() with disk-cache + TTL around it."""
    entry = cache.get(key)
    if not refresh and entry and time.time() - entry.get("ts", 0) < ttl:
        return entry["data"]
    data = fn()
    cache.set(key, {"ts": time.time(), "data": data})
    return data


def du_kb(path):
    """Size of one path in KB (0 if missing/unreadable)."""
    if not os.path.exists(path):
        return 0
    lines = run_lines(["du", "-sxk", str(path)])
    if not lines:
        return 0
    try:
        return int(lines[0].split("\t", 1)[0])
    except (ValueError, IndexError):
        return 0


def du_tree(root, depth):
    """[(kb, path)] for all dirs under root to `depth`, sorted desc."""
    flag = ["-d", str(depth)]
    lines = run_lines(["du", "-xk", *flag, str(root)])
    out = []
    for ln in lines:
        try:
            kb_s, path = ln.split("\t", 1)
            out.append((int(kb_s), path))
        except (ValueError, IndexError):
            continue
    out.sort(reverse=True)
    return out


def drop_redundant_parents(pairs):
    """Drop a parent dir when one listed child explains >85% of its size."""
    drop = set()
    for kb, path in pairs:
        prefix = path + "/"
        for ckb, cpath in pairs:
            if cpath.startswith(prefix) and kb and ckb / kb > 0.85:
                drop.add(path)  # child explains the parent; show the child
                break
    return [(kb, p) for kb, p in pairs if p not in drop]


def dedup_tree(entries, root, top):
    """Top entries, with redundant parents dropped."""
    keep = []
    for kb, path in entries:
        if path == str(root):
            continue
        keep.append((kb, path))
        if len(keep) >= top * 3:  # enough candidates to dedup from
            break
    return drop_redundant_parents(keep)[:top]


def newest_mtime(path):
    """Newest mtime among the dir and its immediate children (heuristic)."""
    try:
        newest = os.stat(path).st_mtime
        with os.scandir(path) as it:
            for child in it:
                try:
                    newest = max(newest, child.stat(follow_symlinks=False).st_mtime)
                except OSError:
                    continue
        return newest
    except OSError:
        return time.time()  # unreadable: treat as fresh, never suggest


def find_large_files(root, min_mb, limit=15):
    lines = run_lines(
        ["find", str(root), "-xdev", "-type", "f", "-size", f"+{min_mb}M"]
    )
    sized = []
    for path in lines:
        try:
            # st_blocks = allocated 512B blocks: real usage, not apparent size
            # (sparse files like Docker.raw report TBs of st_size)
            sized.append((os.stat(path).st_blocks * 512 // 1024, path))
        except OSError:
            continue
    sized.sort(reverse=True)
    return sized[:limit]


def find_named_dirs(root, name, maxdepth=6, limit=50):
    """[(kb, path)] for dirs named `name` under root, largest first."""
    lines = run_lines(
        [
            "find",
            str(root),
            "-xdev",
            "-maxdepth",
            str(maxdepth),
            "-type",
            "d",
            "-name",
            name,
        ]
    )
    sized = [(du_kb(p), p) for p in lines[:limit]]
    sized.sort(reverse=True)
    return [(kb, p) for kb, p in sized if kb > 0]


def parse_size_str(s):
    """Parse strings like '1.234GB', '555MB', '0B' to KB."""
    m = re.match(r"([\d.]+)\s*([KMGT]?)B?", s.strip())
    if not m:
        return 0
    mult = {"": 1 / 1024, "K": 1, "M": 1024, "G": 1024**2, "T": 1024**3}
    return int(float(m.group(1)) * mult[m.group(2)])


def docker_image_kb():
    """Allocated size of docker's backing store: the VM disk image on mac
    (a sparse high-water-mark file that prune does NOT shrink) or
    /var/lib/docker on linux (0 if unreadable without root)."""
    img = HOME / "Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw"
    if img.exists():
        return img.stat().st_blocks * 512 // 1024
    return du_kb("/var/lib/docker")


def docker_status():
    """(state, prunable_kb, image_kb) where state is absent|down|up.

    Not cached: daemon state and prunable space change too often, and the
    check is fast (<1s) in every state.
    """
    if not shutil.which("docker"):
        return "absent", 0, 0
    try:
        res = subprocess.run(
            ["docker", "system", "df", "--format", "{{.Reclaimable}}"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "down", 0, docker_image_kb()
    if res.returncode != 0:
        return "down", 0, docker_image_kb()
    lines = [ln for ln in res.stdout.split("\n") if ln]
    prunable = sum(parse_size_str(ln.split("(")[0]) for ln in lines)
    return "up", prunable, docker_image_kb()


def brew_reclaimable_kb():
    """KB `brew cleanup -n` says it would free (mac only)."""
    if not is_mac or not shutil.which("brew"):
        return 0
    out = cmd("brew cleanup -n 2>/dev/null")
    m = re.search(r"would free approximately ([\d.]+\s*[KMGT]?B)", out)
    return parse_size_str(m.group(1).replace(" ", "")) if m else 0


def rm_contents(path):
    """Delete the contents of a directory, keeping the directory itself."""
    p = Path(path).resolve()
    # Guard: only ever empty deep, user-owned paths
    assert p.is_absolute() and len(p.parts) > 3, f"refusing to clean {p}"
    freed_errors = 0
    for child in p.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except OSError:
            freed_errors += 1
    if freed_errors:
        print(grey_str(f"  ({freed_errors} items skipped: permission/in-use)"))


class Target:
    """A known-reclaimable category: how big it is and how to clean it."""

    def __init__(self, name, kb, clean_fn=None, note="", cache_key=None):
        self.name = name
        self.kb = kb
        self.clean_fn = clean_fn  # None = report-only
        self.note = note
        self.cache_key = cache_key  # busted after cleaning so sizes re-measure


def build_targets(cache, refresh):
    targets = []

    def add_dir(name, path, clean=True, note=""):
        key = f"target:{path}"
        kb = cached(cache, key, lambda: du_kb(path), refresh)
        fn = (lambda p=path: rm_contents(p)) if clean else None
        targets.append(Target(name, kb, fn, note, cache_key=key))

    if is_mac:
        add_dir("Trash", HOME / ".Trash")
        add_dir(
            "User caches (~/Library/Caches)",
            HOME / "Library/Caches",
            note="apps rebuild these",
        )
    else:
        add_dir("Trash", HOME / ".local/share/Trash")
        add_dir("User caches (~/.cache)", HOME / ".cache", note="apps rebuild these")

    npm_dir = HOME / ".npm"
    if npm_dir.exists():
        key = f"target:{npm_dir}"
        kb = cached(cache, key, lambda: du_kb(npm_dir), refresh)
        if shutil.which("npm"):
            fn = lambda: cmd("npm cache clean --force 2>/dev/null")
        else:
            fn = lambda d=npm_dir: rm_contents(d)
        targets.append(Target("npm cache (~/.npm)", kb, fn, cache_key=key))

    for conda_root in (HOME / "miniconda3", HOME / "anaconda3"):
        pkgs = conda_root / "pkgs"
        if pkgs.exists():
            key = f"target:{pkgs}"
            kb = cached(cache, key, lambda p=pkgs: du_kb(p), refresh)
            targets.append(
                Target(
                    f"conda pkgs ({pkgs})",
                    kb,
                    lambda: cmd("conda clean --all -y", noisy=True),
                    note="cached package tarballs",
                    cache_key=key,
                )
            )
            break

    pyc = cached(
        cache,
        "target:__pycache__",
        lambda: find_named_dirs(HOME, "__pycache__"),
        refresh,
    )
    if pyc:

        def clean_pyc(dirs=pyc):
            for _kb, p in dirs:
                shutil.rmtree(p, ignore_errors=True)

        targets.append(
            Target(
                f"__pycache__ dirs ({len(pyc)} found)",
                sum(kb for kb, _ in pyc),
                clean_pyc,
                cache_key="target:__pycache__",
            )
        )

    dstate, dprune, dimg = docker_status()
    if dstate == "up" and dprune:
        targets.append(
            Target(
                "docker (dangling images/containers)",
                dprune,
                lambda: cmd("docker system prune -f", noisy=True),
            )
        )
    if dimg > 1024**2:  # surface the backing store whenever it exceeds 1GB
        if dstate == "up" and not dprune:
            note = "engine is empty; prune can't shrink this high-water-mark file - use Docker Desktop's purge/reset to reclaim"
        elif dstate == "up":
            note = "high-water-mark file; prune frees space inside it but only Docker Desktop purge/reset shrinks it"
        else:
            note = "daemon not running: start docker to measure/prune"
        targets.append(Target("docker disk image", dimg, None, note=note))

    bkb = cached(cache, "target:brew", brew_reclaimable_kb, refresh)
    if bkb:
        targets.append(
            Target(
                "brew cleanup",
                bkb,
                lambda: cmd("brew cleanup", noisy=True),
                cache_key="target:brew",
            )
        )

    tmp_kb = cached(cache, "target:/tmp", lambda: du_kb("/tmp"), refresh, ttl=3600)
    if tmp_kb:
        targets.append(Target("/tmp", tmp_kb, None, note="cleared on reboot"))

    return targets


def all_users_summary():
    """One-line disk summary per user homedir (/Users or /home)."""
    base = Path("/Users" if is_mac else "/home")
    homes = sorted(
        (d for d in base.iterdir() if d.is_dir() and not d.name.startswith(".")),
        key=lambda d: d.name,
    )
    if os.geteuid() != 0:
        print(
            yellow_str(
                "Not running as root: other users' homedirs will be "
                "under-counted. Rerun with: sudo diskfree.py --all-users"
            )
        )
    print(bold_str(f"\nHomedirs under {base}"))
    sized = sorted(((du_kb(d), d) for d in homes), reverse=True)
    for kb, d in sized:
        print(f"  {hsize(kb):>10}  {blue_str(str(d))}")
    print(grey_str("\ndrill in with: [sudo] diskfree.py <homedir>"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "root",
        nargs="?",
        default=str(HOME),
        help="directory to analyze (default: $HOME)",
    )
    p.add_argument(
        "--all-users",
        action="store_true",
        help="summarize every homedir in /Users (mac) or /home (linux); "
        "use with sudo to see other users",
    )
    p.add_argument("--top", type=int, default=15, help="rows per section")
    p.add_argument("--depth", type=int, default=3, help="du scan depth")
    p.add_argument("--refresh", action="store_true", help="ignore cached scans")
    p.add_argument(
        "--stale-days", type=int, default=90, help="age for the large+stale heuristic"
    )
    p.add_argument(
        "--min-file-mb",
        type=int,
        default=250,
        help="threshold for the large-files list",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="offer to clean each reclaimable category (confirmed per item)",
    )
    args = p.parse_args()

    if args.all_users:
        all_users_summary()
        return

    root = Path(args.root).expanduser().resolve()
    # Root gets its own cache: a root-owned cache file would break later
    # unprivileged runs, and sudo sees more so sizes differ anyway.
    cache = DiskCache("diskfree_root" if os.geteuid() == 0 else "diskfree")
    if not os.access(root, os.R_OK):
        print(
            yellow_str(
                f"{root} is not readable; sizes will be incomplete. "
                f"Try: sudo diskfree.py {root}"
            )
        )

    # ---- disk overview ----
    usage = shutil.disk_usage(root)
    pct = 100 * usage.used / usage.total
    color = red_str if pct > 90 else (yellow_str if pct > 75 else green_str)
    print(bold_str(f"\nDisk containing {root}"))
    print(
        f"  {color(f'{pct:.0f}% used')} - "
        f"{size_to_human(usage.used)} of {size_to_human(usage.total)}, "
        f"{green_str(size_to_human(usage.free))} free"
    )

    # ---- largest directories (cached) ----
    print(
        grey_str("\nscanning... (cached for 12h, --refresh to rescan)"), file=sys.stderr
    )
    tree = cached(
        cache,
        f"tree:{root}:{args.depth}",
        lambda: du_tree(root, args.depth),
        args.refresh,
    )
    entries = [(kb, p) for kb, p in tree]
    print(bold_str("\nLargest directories"))
    for kb, path in dedup_tree(entries, root, args.top):
        print(f"  {hsize(kb):>10}  {blue_str(path)}")

    # ---- large + stale dirs ----
    cutoff = time.time() - args.stale_days * 86400
    stale = []
    for kb, path in entries[:200]:
        if kb < 1024**2 or path == str(root):  # only dirs >= 1GB
            continue
        if newest_mtime(path) < cutoff:
            stale.append((kb, path))
    stale = drop_redundant_parents(stale)
    if stale:
        print(
            bold_str(f"\nLarge dirs untouched in {args.stale_days}+ days")
            + grey_str("  (heuristic: check before deleting)")
        )
        for kb, path in stale[: args.top]:
            print(f"  {hsize(kb):>10}  {yellow_str(path)}")

    # ---- large files ----
    big_files = cached(
        cache,
        f"files:{root}:{args.min_file_mb}",
        lambda: find_large_files(root, args.min_file_mb),
        args.refresh,
    )
    if big_files:
        print(bold_str(f"\nFiles over {args.min_file_mb}MB"))
        for kb, path in big_files[: args.top]:
            print(f"  {hsize(kb):>10}  {path}")

    # ---- reclaimable ----
    targets = build_targets(cache, args.refresh)
    targets.sort(key=lambda t: t.kb, reverse=True)
    cleanable_kb = sum(t.kb for t in targets if t.clean_fn)
    print(bold_str("\nReclaimable"))
    for t in targets:
        tag = "" if t.clean_fn else grey_str(" [report-only]")
        note = grey_str(f"  ({t.note})") if t.note else ""
        print(f"  {hsize(t.kb):>10}  {t.name}{tag}{note}")
    print(
        f"  {green_str(hsize(cleanable_kb)):>10}  "
        + bold_str("total cleanable")
        + ("" if args.clean else grey_str("  -> rerun with --clean to reclaim"))
    )

    # ---- gated cleaning ----
    if args.clean:
        print()
        freed = 0
        for t in targets:
            if not t.clean_fn or not t.kb:
                continue
            if yes_or_no(f"Clean {t.name} ({hsize(t.kb)})?"):
                t.clean_fn()
                freed += t.kb
                # bust this target's cached size so the next run re-measures
                if t.cache_key:
                    cache.set(t.cache_key, {"ts": 0, "data": 0})
        if freed:
            print(green_str(f"\nFreed approximately {hsize(freed)}"))


if __name__ == "__main__":
    main()
