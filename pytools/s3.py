#!/usr/bin/env python3

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from PIL import Image
from srutils import cmd, log

logging.getLogger("botocore").setLevel(logging.WARNING)
s3 = boto3.client("s3")
base_tempdir = Path("/tmp/")


def parse_s3_path(path: str) -> tuple[str, str]:
    """Parse s3 path into bucket and key. Accepts s3://b/k, /b/k, or b/k."""
    path = path.removeprefix("s3://").lstrip("/")
    bucket, *key_parts = path.split("/")
    key = "/".join(key_parts)
    return bucket, key


def download_from_s3(bucket_name: str, s3_key: str, local_path: str):
    """Download s3 object to a specific path"""
    try:
        s3.download_file(bucket_name, s3_key, local_path)
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            log.warning(f"File Does not exist: s3://{bucket_name}/{s3_key}")
            return False
        else:
            raise
    return True


def get_etag(bucket_name, s3_key):
    response = s3.head_object(Bucket=bucket_name, Key=s3_key)
    return response.get("ETag").strip('"')


def get_s3_cached(bucket_name, s3_key, use_cache=True, check_etag=True):
    """Download s3 object to tempdir with caching"""
    local_path = base_tempdir / "s3" / bucket_name / s3_key
    local_path.parent.mkdir(parents=True, exist_ok=True)
    in_cache = use_cache and os.path.exists(local_path)

    etag_path = f"{local_path}.etag"
    remote_etag = None
    if in_cache and check_etag:
        if not os.path.exists(etag_path):
            in_cache = False
        else:
            local_etag = open(etag_path, "r").read().strip()
            remote_etag = get_etag(bucket_name, s3_key)
            if local_etag != remote_etag:
                log.debug("S3 object is cached but etag differs")
                in_cache = False

    if in_cache:
        log.debug(f"S3 object already downloaded: {local_path}")
        return local_path

    # Download direct from s3
    print(f"Downloading s3://{bucket_name}/{s3_key}...", file=sys.stderr)
    res = download_from_s3(bucket_name, s3_key, local_path)
    if not res:
        return None

    # Write etag to local path
    if not remote_etag:
        remote_etag = get_etag(bucket_name, s3_key)
    open(etag_path, "w").write(remote_etag)

    return local_path


def human_size(nbytes):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f}{unit}" if unit != "B" else f"{nbytes}B"
        nbytes /= 1024
    return f"{nbytes:.1f}PB"


def format_obj(obj, prefix=""):
    date = obj["LastModified"].strftime("%Y-%m-%d %H:%M")
    name = obj["Key"].removeprefix(prefix)
    return f"{date}  {human_size(obj['Size']):>10s}  {name}"


def list_s3(bucket_name: str, prefix: str, recursive=False, full_path=False):
    """List s3 objects in path."""
    strip = "" if full_path else prefix
    paginator = s3.get_paginator("list_objects_v2")
    if recursive:
        result = []
        for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
            for obj in page.get("Contents", []):
                result.append(format_obj(obj, strip))
        return result
    else:
        result = []
        for page in paginator.paginate(
            Bucket=bucket_name, Prefix=prefix, Delimiter="/"
        ):
            for p in page.get("CommonPrefixes", []):
                result.append(f"{'':>28s}{p['Prefix'].removeprefix(strip)}")

            for obj in page.get("Contents", []):
                key = obj["Key"]
                if (
                    not prefix
                    or key == prefix
                    or (
                        key.startswith(prefix)
                        and key.replace(prefix, "").count("/") <= 1
                        and not key.replace(prefix, "").startswith("/")
                    )
                ):
                    result.append(format_obj(obj, strip))

        return result


def list_buckets():
    """List all S3 buckets."""
    response = s3.list_buckets()
    buckets = response.get("Buckets", [])
    if not buckets:
        print("No buckets found.")
        return
    for b in buckets:
        date = b["CreationDate"].strftime("%Y-%m-%d %H:%M")
        print(f"{date}  {b['Name']}")


def show_metadata(bucket_name: str, s3_key: str, head: dict, local_path: str):
    """Show file metadata; runs ffprobe on local cached file."""
    size = head["ContentLength"]
    date = head["LastModified"].strftime("%Y-%m-%d %H:%M")
    content_type = head.get("ContentType", "unknown")
    print(f"  path:         s3://{bucket_name}/{s3_key}")
    print(f"  size:         {human_size(size)}")
    print(f"  modified:     {date}")
    print(f"  content-type: {content_type}")

    if subprocess.run(["which", "ffprobe"], capture_output=True).returncode != 0:
        return

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "flat",
            "-show_format",
            "-show_streams",
            local_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return

    # Print a clean subset of the ffprobe flat output
    keep = {"format.duration", "format.bit_rate", "format.size"}
    for line in result.stdout.splitlines():
        key_part = line.split("=")[0]
        if (
            any(
                x in key_part
                for x in (
                    "codec_name",
                    "codec_type",
                    "sample_rate",
                    "channels",
                    "width",
                    "height",
                    "r_frame_rate",
                    "bit_rate",
                    "duration",
                )
            )
            or key_part in keep
        ):
            val = line.split("=", 1)[1].strip('"') if "=" in line else ""
            print(f"  {key_part:<35} {val}")


def play_media(local_path: str, is_video: bool):
    """Play audio or video file, cross-platform."""
    path = str(local_path)
    if sys.platform == "darwin":
        if is_video:
            cmd(f"open {path}", noisy=True)
        else:
            cmd(f"afplay {path}", noisy=True)
    else:
        # Linux: try mpv, ffplay, vlc in order
        for player in ("mpv", "ffplay", "vlc"):
            if subprocess.run(["which", player], capture_output=True).returncode == 0:
                cmd(f"{player} {path}", noisy=True)
                return
        log.error(
            "No media player found (tried mpv, ffplay, vlc). Install one or use --metadata."
        )


def show_size(bucket_name: str, key: str, recursive: bool):
    """Print size of a file or folder."""
    from s3_size import get_size_recursive

    if not key or key.endswith("/"):
        prefix = key
        print(f"Calculating size of s3://{bucket_name}/{prefix}...", file=sys.stderr)
        total_gb, count = get_size_recursive(bucket_name, prefix)
        print(f"\nTotal objects: {count}")
        print(f"Total size:    {total_gb * 1024:.2f} MB  ({total_gb:.3f} GB)")
    else:
        try:
            head = s3.head_object(Bucket=bucket_name, Key=key)
            size = head["ContentLength"]
            date = head["LastModified"].strftime("%Y-%m-%d %H:%M")
            print(f"{date}  {human_size(size):>10s}  s3://{bucket_name}/{key}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                # Try as folder
                prefix = key + "/"
                print(
                    f"Calculating size of s3://{bucket_name}/{prefix}...",
                    file=sys.stderr,
                )
                total_gb, count = get_size_recursive(bucket_name, prefix)
                print(f"\nTotal objects: {count}")
                print(f"Total size:    {total_gb * 1024:.2f} MB  ({total_gb:.3f} GB)")
            else:
                raise


def main():
    parser = argparse.ArgumentParser(description="Browse and inspect S3 objects")
    parser.add_argument("path", nargs="?", help="S3 path: s3://b/k, /b/k, or b/k")
    parser.add_argument("--bucket", "-b", help="S3 bucket name")
    parser.add_argument("--key", "-k", help="S3 key")
    parser.add_argument("--verbose", action="store_true", help="print all files")
    parser.add_argument(
        "--recursive", "-r", action="store_true", help="list recursively"
    )
    parser.add_argument(
        "--force", "-f", action="store_true", help="download even if large or binary"
    )
    parser.add_argument(
        "--full-path", action="store_true", help="show full keys in listings"
    )
    parser.add_argument(
        "--metadata",
        "-m",
        action="store_true",
        help="show media metadata via ffprobe (no download)",
    )
    parser.add_argument(
        "--play", "-p", action="store_true", help="play audio/video file"
    )
    parser.add_argument(
        "--size", "-s", action="store_true", help="show size (recursive for folders)"
    )
    args = parser.parse_args()

    # No args → list buckets
    if not args.bucket and not args.path:
        list_buckets()
        return

    if args.bucket:
        bucket, key = args.bucket, args.key or ""
    else:
        bucket, key = parse_s3_path(args.path)

    log.debug(f"{bucket=} {key=}")

    # --size: just report size and exit
    if args.size:
        show_size(bucket, key, args.recursive)
        return

    fp = args.full_path
    if not key or key.endswith("/"):
        log.info(f"\ns3://{bucket}/{key}:")
        for item in list_s3(bucket, key, recursive=args.recursive, full_path=fp):
            log.info(item)
        return

    BINARY_EXTS = {
        ".tar.gz",
        ".tgz",
        ".gz",
        ".zip",
        ".bz2",
        ".xz",
        ".7z",
        ".jar",
        ".war",
        ".ear",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".dat",
        ".pkl",
        ".pickle",
        ".parquet",
        ".avro",
        ".orc",
    }
    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}
    AUDIO_EXTS = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".aiff", ".opus"}
    VIDEO_EXTS = {
        ".mp4",
        ".mkv",
        ".mov",
        ".avi",
        ".webm",
        ".m4v",
        ".wmv",
        ".flv",
        ".ts",
    }
    MAX_SIZE = 50 * 1024 * 1024

    is_binary = any(key.endswith(ext) for ext in BINARY_EXTS)
    is_image = any(key.endswith(ext) for ext in IMAGE_EXTS)
    is_audio = any(key.endswith(ext) for ext in AUDIO_EXTS)
    is_video = any(key.endswith(ext) for ext in VIDEO_EXTS)
    is_media = is_audio or is_video

    # Check size/existence before downloading
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            items = list_s3(bucket, key + "/", recursive=args.recursive, full_path=fp)
            if items:
                log.info(f"\ns3://{bucket}/{key}/:")
                for item in items:
                    log.info(item)
                return
            log.error(f"Not found: s3://{bucket}/{key}")
            return
        raise

    size = head["ContentLength"]
    date = head["LastModified"].strftime("%Y-%m-%d %H:%M")

    if not args.force and (size > MAX_SIZE or is_binary) and not is_media:
        log.info(f"{date}  {human_size(size):>10s}  s3://{bucket}/{key}")
        if size > MAX_SIZE:
            log.info(
                f"File too large to auto-download ({human_size(size)}). Use --force to download."
            )
        if is_binary:
            log.info("Binary file type. Use --force to download.")
        return

    local_path = str(get_s3_cached(bucket, key))

    if is_image:
        print(f"Opening image: {local_path}", file=sys.stderr)
        img = Image.open(local_path)
        img.show()
    elif is_media:
        # Default: metadata. --play to play.
        if args.play:
            print(f"Playing: {local_path}", file=sys.stderr)
            play_media(local_path, is_video)
        else:
            show_metadata(bucket, key, head, local_path)
    else:
        cmd(f"cat {local_path}", noisy=True)


if __name__ == "__main__":
    main()
