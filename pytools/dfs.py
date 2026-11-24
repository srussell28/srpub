#!/usr/bin/env python3

import shutil
from dataclasses import dataclass

from srutils import cmd, to_metric_base

ONE_GB = 1024**3
TEN_GB = 10368709120


def df_filtered():
    resp = cmd("df -h")
    lines = resp.splitlines()
    print(lines[0])
    for line in lines[1:]:
        parts = line.split()
        filesys = parts[0]
        if not filesys.startswith("/"):
            continue
        size_bytes = to_metric_base(parts[1])
        if size_bytes < TEN_GB:
            continue
        print(line)


def percent_bar(percentage, width=20):
    """
    Create a simple text progress bar.

    :param percentage: Usage percentage (0-100)
    :param width: Width of the bar in characters
    :return: A string with a progress bar and percentage label.
    """
    filled_length = int(round(width * percentage / 100))
    bar = "x" * filled_length + "_" * (width - filled_length)
    return f"[{bar}]"


@dataclass
class DiskUsage:
    total: int
    used: int
    free: int
    percent: float


def get_disk_usage(path: str = "/") -> DiskUsage:
    """Get disk usage statistics for the specified path.

    Args:
        path: Path to check disk usage for

    Returns:
        DiskUsage object with total, used, free space (in bytes) and usage percent
    """
    total, used, free = shutil.disk_usage(path)
    percent = (used / total) * 100
    return DiskUsage(total, used, free, percent)


# Example usage
if __name__ == "__main__":
    df_filtered()
    print("\n\n")

    for mount in ["/"]:
        try:
            usage = get_disk_usage(mount)
            free_percent = 100.0 - usage.percent
            print(f"{mount}")
            print(f"  {percent_bar(usage.percent, width=30)}\n")
            print(f"  Total: {usage.total / ONE_GB:.1f} GB")
            print(f"  Used:  {usage.used / ONE_GB:.1f} GB  {usage.percent:.1f}%")
            print(f"  Free:  {usage.free / ONE_GB:.1f} GB  {free_percent:.1f}%")
        except (PermissionError, OSError):
            continue
