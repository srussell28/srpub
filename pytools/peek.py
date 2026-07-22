#!/usr/bin/env python3
"""
peek PATH  — smart local file/directory explorer.

Picks a viewer based on what the path is:
  directory       → rich ls listing
  *.md            → glow (fallback: cat)
  *.json, *.jsonl → jq color (fallback: python pretty-print)
  *.py / code     → bat syntax highlight (fallback: cat)
  *.csv           → tabular preview
  image           → PIL metadata
  audio/video     → ffprobe metadata
  *.zip / *.tar   → list contents
  text            → cat (truncated if large)
  binary          → file(1) info + hex sample
"""

import argparse
import csv
import mimetypes
import shutil
import subprocess
import sys
import zipfile
import tarfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(cmd, **kwargs):
    return subprocess.run(cmd, **kwargs)


def has(tool):
    return shutil.which(tool) is not None


def file_size_str(n):
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}P"


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_directory(path: Path, ls_args: list):
    cmd = ["ls"]
    if sys.platform == "darwin":
        cmd += ["-G"]
    else:
        cmd += ["--color=auto"]
    cmd += ls_args + [str(path)]
    run(cmd)


def handle_markdown(path: Path):
    if has("glow"):
        run(["glow", str(path)])
    else:
        print(path.read_text(), end="")


def handle_json(path: Path):
    if has("jq"):
        run(["jq", "-C", ".", str(path)])
    else:
        import json

        try:
            data = json.loads(path.read_text())
            print(json.dumps(data, indent=2))
        except json.JSONDecodeError as e:
            print(f"Invalid JSON: {e}", file=sys.stderr)
            print(path.read_text(), end="")


def handle_jsonl(path: Path):
    import json

    lines = path.read_text().strip().splitlines()
    print(f"({len(lines)} lines)")
    for line in lines[:20]:
        try:
            obj = json.loads(line)
            if has("jq"):
                result = subprocess.run(
                    ["jq", "-C", "-c", "."],
                    input=json.dumps(obj),
                    capture_output=True,
                    text=True,
                )
                print(result.stdout, end="")
            else:
                print(json.dumps(obj))
        except json.JSONDecodeError:
            print(line)
    if len(lines) > 20:
        print(f"  ... ({len(lines) - 20} more lines)")


CODE_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".java",
    ".rb",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".tf",
    ".sql",
    ".html",
    ".css",
    ".scss",
    ".proto",
    ".thrift",
    ".vue",
    ".astro",
}


def handle_code(path: Path):
    if has("bat"):
        run(["bat", "--style=plain,header", "--color=always", str(path)])
    else:
        print(path.read_text(), end="")


def handle_text(path: Path, max_lines=200):
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    if len(lines) > max_lines:
        for line in lines[:max_lines]:
            print(line)
        print(f"\n  ... ({len(lines) - max_lines} more lines, use --all to show all)")
    else:
        print(text, end="")


def handle_csv(path: Path, max_rows=20):
    with open(path, newline="", errors="replace") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        print("(empty)")
        return
    header = rows[0]
    data = rows[1:]
    print(f"  {len(data)} rows × {len(header)} cols")
    print()
    # Column widths
    col_w = [len(h) for h in header]
    for row in data[:max_rows]:
        for i, cell in enumerate(row):
            if i < len(col_w):
                col_w[i] = max(col_w[i], min(len(cell), 30))
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in col_w)
    print("\033[1m" + fmt.format(*[h[:30] for h in header]) + "\033[0m")
    print("  " + "  ".join("-" * w for w in col_w))
    for row in data[:max_rows]:
        padded = [row[i] if i < len(row) else "" for i in range(len(header))]
        print(fmt.format(*[c[:30] for c in padded]))
    if len(data) > max_rows:
        print(f"  ... ({len(data) - max_rows} more rows)")


IMAGE_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".tiff",
    ".tif",
    ".heic",
    ".avif",
}


def handle_image(path: Path):
    try:
        from PIL import Image

        img = Image.open(path)
        print(f"  Format:     {img.format}")
        print(f"  Mode:       {img.mode}")
        print(f"  Dimensions: {img.width} × {img.height}")
        print(f"  File size:  {file_size_str(path.stat().st_size)}")
        if hasattr(img, "_getexif") and img._getexif():
            from PIL.ExifTags import TAGS

            exif = {TAGS.get(k, k): v for k, v in img._getexif().items()}
            for tag in ("DateTime", "Make", "Model", "GPSInfo"):
                if tag in exif:
                    print(f"  {tag + ':':<12} {exif[tag]}")
    except Exception as e:
        print(f"  {file_size_str(path.stat().st_size)}")
        print(f"  (PIL error: {e})")


MEDIA_EXTS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".m4v",
    ".flv",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".wav",
    ".ogg",
    ".opus",
}


def handle_media(path: Path):
    if has("ffprobe"):
        run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ]
        )
    else:
        print(f"  {file_size_str(path.stat().st_size)}")
        print("  (install ffprobe for media metadata)")


def handle_zip(path: Path):
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            print(f"  {len(infos)} entries")
            for info in infos[:50]:
                size = file_size_str(info.file_size)
                print(f"  {size:>7}  {info.filename}")
            if len(infos) > 50:
                print(f"  ... ({len(infos) - 50} more)")
    except zipfile.BadZipFile as e:
        print(f"  Bad zip: {e}")


def handle_tar(path: Path):
    try:
        with tarfile.open(path) as tf:
            members = tf.getmembers()
            print(f"  {len(members)} entries")
            for m in members[:50]:
                size = file_size_str(m.size) if m.isfile() else ""
                print(f"  {size:>7}  {m.name}{'/' if m.isdir() else ''}")
            if len(members) > 50:
                print(f"  ... ({len(members) - 50} more)")
    except Exception as e:
        print(f"  Error reading tar: {e}")


def handle_binary(path: Path):
    result = subprocess.run(["file", str(path)], capture_output=True, text=True)
    print(f"  {result.stdout.strip()}")
    print(f"  Size: {file_size_str(path.stat().st_size)}")
    # Hex sample
    data = path.read_bytes()[:64]
    hex_str = " ".join(f"{b:02x}" for b in data)
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    print(f"\n  {hex_str}")
    print(f"  {printable}")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def peek(path: Path, show_all: bool = False, ls_args: list = None):
    if not path.exists():
        print(f"peek: {path}: no such file or directory", file=sys.stderr)
        sys.exit(1)

    if path.is_dir():
        handle_directory(path, ls_args or [])
        return

    ext = path.suffix.lower()
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or ""

    print(f"\033[1m{path}\033[0m  ({file_size_str(path.stat().st_size)})\n")

    if ext == ".md":
        handle_markdown(path)
    elif ext == ".jsonl":
        handle_jsonl(path)
    elif ext == ".json" or mime == "application/json":
        handle_json(path)
    elif ext == ".csv" or mime == "text/csv":
        handle_csv(path)
    elif ext in IMAGE_EXTS or mime.startswith("image/"):
        handle_image(path)
    elif ext in MEDIA_EXTS or mime.startswith(("video/", "audio/")):
        handle_media(path)
    elif ext in (".zip",):
        handle_zip(path)
    elif ext in (".tar", ".gz", ".tgz", ".bz2", ".xz") or str(path).endswith(
        (".tar.gz", ".tar.bz2", ".tar.xz")
    ):
        handle_tar(path)
    elif ext in CODE_EXTS:
        handle_code(path)
    elif mime.startswith("text/") or ext in (".txt", ".log", ".env", ".gitignore"):
        if show_all:
            print(path.read_text(errors="replace"), end="")
        else:
            handle_text(path)
    else:
        # Try to read as text, fall back to binary
        try:
            path.read_text(errors="strict")
            if show_all:
                print(path.read_text(errors="replace"), end="")
            else:
                handle_text(path)
        except UnicodeDecodeError:
            handle_binary(path)


def main():
    parser = argparse.ArgumentParser(description="Smart local file explorer.")
    parser.add_argument(
        "path", nargs="?", default=".", help="File or directory to peek at"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Show full content without truncation (files only)",
    )
    args, extra = parser.parse_known_args()
    peek(Path(args.path), show_all=args.all, ls_args=extra)


if __name__ == "__main__":
    main()
