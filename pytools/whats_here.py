#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import sys
from collections import defaultdict


def is_binary_file(file_path):
    """Check if a file is binary using the 'file' command."""
    try:
        # Use the file command to determine file type
        result = subprocess.run(
            ["file", "--mime-encoding", "-b", file_path],
            capture_output=True,
            text=True,
            check=False,
        )

        # If the encoding contains 'binary', it's a binary file
        if "binary" in result.stdout.lower():
            return True

        # Common binary extensions
        binary_extensions = {
            "jpg",
            "jpeg",
            "png",
            "gif",
            "bmp",
            "ico",
            "mp3",
            "mp4",
            "avi",
            "mov",
            "pdf",
            "doc",
            "docx",
            "xls",
            "xlsx",
            "zip",
            "tar",
            "gz",
            "rar",
            "bin",
            "exe",
            "so",
            "dll",
            "o",
            "pyc",
            "class",
            "jar",
            "woff",
            "ttf",
            "eot",
        }

        # Check extension
        _, ext = os.path.splitext(file_path)
        if ext and ext[1:].lower() in binary_extensions:
            return True

        return False
    except Exception:
        # If there's an error, default to False
        return False


def count_lines(file_path, skip_binary=False):
    """Count the number of lines in a file."""
    try:
        # Skip counting lines for binary files
        if skip_binary and is_binary_file(file_path):
            return 0

        with open(file_path, "rb") as f:
            return sum(1 for _ in f)
    except (OSError, UnicodeDecodeError, IsADirectoryError):
        return 0


def get_extension(file_path):
    """Get the extension of a file, or classify it if it has no extension."""
    _, ext = os.path.splitext(file_path)
    if ext:
        return ext[1:].lower()  # Remove the dot
    else:
        # Check if it's executable
        if os.access(file_path, os.X_OK):
            return "executable"
        return "no_ext"


def is_test_file(file_path):
    """Check if a file is a test file based on its name."""
    file_name = os.path.basename(file_path)
    return bool(re.search(r"test", file_name, re.IGNORECASE))


def is_dot_file(file_path):
    """Check if a file is a dot file based on its name."""
    file_name = os.path.basename(file_path)
    return file_name.startswith(".")


def analyze_directory(path, additional_ignore_dirs=None, skip_binary=False):
    """Recursively analyze a directory and return file statistics."""
    stats = {
        "regular": defaultdict(
            lambda: {"count": 0, "lines": 0, "size": 0, "files": []}
        ),
        "test": defaultdict(lambda: {"count": 0, "lines": 0, "size": 0, "files": []}),
        "dotfiles": defaultdict(
            lambda: {"count": 0, "lines": 0, "size": 0, "files": []}
        ),
        "binary": defaultdict(lambda: {"count": 0, "lines": 0, "size": 0, "files": []}),
    }

    # Directories to ignore
    ignore_dirs = {
        "vendor",
        "node_modules",
        "build",
        ".meteor",
        ".mypy_cache",
        ".env",
        "bazel-venvs",
        "__pycache__",
        "venv",
        ".venv",
        "dist",
        "target",
        ".git",
        ".idea",
        ".vscode",
    }

    # Add additional directories to ignore
    if additional_ignore_dirs:
        ignore_dirs.update(additional_ignore_dirs)

    total_files = 0
    total_lines = 0
    total_size = 0

    for root, dirs, files in os.walk(path):
        # Skip ignored directories
        dirs[:] = [d for d in dirs if d not in ignore_dirs]

        for file in files:
            file_path = os.path.join(root, file)

            # Skip symlinks
            if os.path.islink(file_path):
                continue

            total_files += 1

            try:
                # Get file size
                file_size = os.path.getsize(file_path)
                total_size += file_size

                lines = count_lines(file_path, skip_binary)
                total_lines += lines

                extension = get_extension(file_path)

                # Determine category
                is_binary = is_binary_file(file_path)

                if is_binary:
                    category = "binary"
                elif is_test_file(file_path):
                    category = "test"
                elif is_dot_file(file_path):
                    category = "dotfiles"
                else:
                    category = "regular"

                # Update stats
                stats[category][extension]["count"] += 1
                stats[category][extension]["lines"] += lines
                stats[category][extension]["size"] += file_size
                stats[category][extension]["files"].append(file_path)

            except Exception as e:
                print(f"Error processing {file_path}: {e}", file=sys.stderr)

    return stats, total_files, total_lines, total_size


def format_size(size_bytes):
    """Format size in bytes to a human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def print_stats(stats, total_files, total_lines, total_size, path, sort_by="count"):
    """Print the statistics in a readable format."""
    print(f"Analysis of '{path}':")
    print(f"Total files: {total_files}")
    print(f"Total lines: {total_lines}")
    print(f"Total size: {format_size(total_size)}")
    print("\n" + "=" * 80)

    categories = [
        ("Regular Files", "regular"),
        ("Test Files", "test"),
        ("Binary Files", "binary"),
        ("Dotfiles", "dotfiles"),
    ]

    # Find the longest extension name for alignment
    max_ext_len = 0
    for category in stats.values():
        for ext in category.keys():
            max_ext_len = max(max_ext_len, len(ext))

    # Add padding and minimum width for extensions
    max_ext_len = max(max_ext_len + 2, 12)

    # Fixed column widths
    cnt_width = 8  # Width for the count numbers
    pct_width = 8  # Width for percentages
    fmt_width = 10  # Width for formatted sizes

    # Calculate total widths
    ext_col_width = max_ext_len
    count_col_width = cnt_width + pct_width + 3  # +3 for spacing and brackets
    lines_col_width = cnt_width + pct_width + 3
    size_col_width = fmt_width + pct_width + 3

    for title, category in categories:
        category_stats = stats[category]
        if not category_stats:
            continue

        category_files = sum(stat["count"] for stat in category_stats.values())
        category_lines = sum(stat["lines"] for stat in category_stats.values())
        category_size = sum(stat["size"] for stat in category_stats.values())

        print(f"\n{title}:")

        # Print table header with fixed column widths
        header = (
            f"  {'Extension':<{ext_col_width}} │ "
            f"{'Files':^{count_col_width}} │ "
            f"{'Lines':^{lines_col_width}} │ "
            f"{'Size':^{size_col_width}}"
        )
        separator = f"  {'-' * ext_col_width}-┼-{'-' * count_col_width}-┼-{'-' * lines_col_width}-┼-{'-' * size_col_width}"

        print(header)
        print(separator)

        # Print total row
        file_percent = 100 * (category_files / total_files) if total_files else 0
        line_percent = 100 * (category_lines / total_lines) if total_lines else 0
        size_percent = 100 * (category_size / total_size) if total_size else 0

        file_part = f"{category_files:>{cnt_width}} ({file_percent:>5.1f}%)"
        line_part = f"{category_lines:>{cnt_width}} ({line_percent:>5.1f}%)"
        size_part = f"{format_size(category_size):>{fmt_width}} ({size_percent:>5.1f}%)"

        total_row = (
            f"  {'TOTAL':<{ext_col_width}} │ "
            f"{file_part:^{count_col_width}} │ "
            f"{line_part:^{lines_col_width}} │ "
            f"{size_part:^{size_col_width}}"
        )
        print(total_row)

        # Sort extensions by file count, line count, or size, descending
        sort_key = sort_by

        sorted_extensions = sorted(
            category_stats.items(), key=lambda x: (x[1][sort_key], x[0]), reverse=True
        )

        for ext, data in sorted_extensions:
            file_count = data["count"]
            line_count = data["lines"]
            size_bytes = data["size"]

            # Calculate percentage of files, lines, and size
            file_percent = (file_count / total_files) * 100 if total_files else 0
            line_percent = (line_count / total_lines) * 100 if total_lines else 0
            size_percent = (size_bytes / total_size) * 100 if total_size else 0

            # Format each part consistently
            file_part = f"{file_count:>{cnt_width}} ({file_percent:>5.1f}%)"
            line_part = f"{line_count:>{cnt_width}} ({line_percent:>5.1f}%)"
            size_part = (
                f"{format_size(size_bytes):>{fmt_width}} ({size_percent:>5.1f}%)"
            )

            print(
                f"  {ext:<{ext_col_width}} │ "
                f"{file_part:^{count_col_width}} │ "
                f"{line_part:^{lines_col_width}} │ "
                f"{size_part:^{size_col_width}}"
            )


def main():
    parser = argparse.ArgumentParser(
        description="Analyze directory contents by file type with statistics."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to directory to analyze (default: current directory)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show file paths for each category"
    )
    parser.add_argument(
        "--ignore",
        "-i",
        nargs="+",
        default=[],
        help="Additional directories to ignore (space separated)",
    )
    parser.add_argument(
        "--sort",
        "-s",
        choices=["count", "lines", "size"],
        default="count",
        help="Sort extensions by file count, line count, or size (default: count)",
    )
    parser.add_argument(
        "--skip-binary",
        "-b",
        action="store_true",
        help="Skip detailed scanning of binary files",
    )

    args = parser.parse_args()

    # Normalize and expand path
    path = os.path.abspath(os.path.expanduser(args.path))

    if not os.path.exists(path):
        print(f"Error: Path '{path}' does not exist", file=sys.stderr)
        return 1

    if not os.path.isdir(path):
        print(f"Error: '{path}' is not a directory", file=sys.stderr)
        return 1

    try:
        stats, total_files, total_lines, total_size = analyze_directory(
            path, args.ignore, args.skip_binary
        )
        print_stats(stats, total_files, total_lines, total_size, path, args.sort)

        if args.verbose:
            print("\n" + "=" * 50)
            print("Detailed file list:")
            for category_name, category_data in stats.items():
                for ext, data in category_data.items():
                    if data["files"]:
                        print(f"\n{category_name.capitalize()} - .{ext}:")
                        for file_path in data["files"]:
                            print(f"  {file_path}")

        return 0

    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
