#!/usr/bin/env python3
import sys
import warnings
from datetime import datetime

import pytz
from dateutil import parser
from dateutil.parser import UnknownTimezoneWarning

warnings.simplefilter("error", UnknownTimezoneWarning)

# Common US/UTC timezone abbreviations not recognized by dateutil by default.
# Values are fixed UTC offsets in seconds.
TZINFOS = {
    "EST": -5 * 3600,
    "EDT": -4 * 3600,
    "CST": -6 * 3600,
    "CDT": -5 * 3600,
    "MST": -7 * 3600,
    "MDT": -6 * 3600,
    "PST": -8 * 3600,
    "PDT": -7 * 3600,
    "UTC": 0,
    "GMT": 0,
}


def try_epoch(datetime_str, quiet=False):
    """Try to interpret as epoch seconds or milliseconds."""
    try:
        val = int(datetime_str)
    except ValueError:
        try:
            val = float(datetime_str)
        except ValueError:
            return None
    # epoch ms if value is too large for seconds (after year 2100 in seconds)
    if val > 4_102_444_800:
        val = val / 1000.0
        if not quiet:
            print("Interpreting as epoch milliseconds")
    else:
        if not quiet:
            print("Interpreting as epoch seconds")
    return datetime.fromtimestamp(val, tz=pytz.UTC)


def normalize_tz_abbrevs(s: str) -> str:
    """Uppercase any trailing timezone abbreviation so dateutil's tzinfos dict matches."""
    parts = s.rsplit(None, 1)
    if len(parts) == 2 and parts[1].upper() in TZINFOS:
        return parts[0] + " " + parts[1].upper()
    return s


def parse_and_convert(datetime_str, show_relative=True, quiet=False):
    # Try to parse the datetime string
    try:
        # Try epoch first for pure numeric input
        dt = try_epoch(datetime_str, quiet=quiet)
        if dt is None:
            datetime_str = normalize_tz_abbrevs(datetime_str)
            # Parse the datetime - dateutil.parser handles many formats
            dt = parser.parse(datetime_str, tzinfos=TZINFOS)

            # If no timezone info, assume UTC
            if dt.tzinfo is None:
                print("Assuming input is UTC")
                dt = pytz.UTC.localize(dt)

        # Convert to the machine's local timezone. A no-arg astimezone() uses
        # the system zone and is DST-correct for the given instant, so this
        # works on any host instead of being pinned to one region.
        local_dt = dt.astimezone()

        # Convert to UTC and to US/Eastern (shown as an extra reference when the
        # local machine isn't already on Eastern time).
        utc_dt = dt.astimezone(pytz.UTC)
        eastern_dt = dt.astimezone(pytz.timezone("US/Eastern"))

        # Format outputs
        print("")
        epoch_s = int(utc_dt.timestamp())
        epoch_ms = int(utc_dt.timestamp() * 1000)
        print(f"Local (24h): {local_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"Local (12h): {local_dt.strftime('%Y-%m-%d %I:%M:%S %p %Z')}")
        # Skip only when the machine actually is on Eastern time. Match both
        # offset and abbreviation so a zone that merely shares Eastern's offset
        # right now (e.g. AST == EDT in summer) still gets the reference line.
        local_is_eastern = (
            local_dt.utcoffset() == eastern_dt.utcoffset()
            and local_dt.tzname() == eastern_dt.tzname()
        )
        if not local_is_eastern:
            print(f"US/Eastern:  {eastern_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"UTC:         {utc_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"Epoch (s):   {epoch_s}")
        print(f"Epoch (ms):  {epoch_ms}")

        if show_relative:
            delta = int(utc_dt.timestamp() - datetime.now(pytz.UTC).timestamp())
            suffix = "from now" if delta >= 0 else "ago"
            secs = abs(delta)
            d, rem = divmod(secs, 86400)
            h, rem = divmod(rem, 3600)
            m, s = divmod(rem, 60)
            parts = [f"{d}d", f"{h}h", f"{m}m", f"{s}s"]
            while len(parts) > 1 and parts[0].startswith("0"):
                parts.pop(0)
            print(f"Relative:    {secs}s ({' '.join(parts)}) {suffix}")

    except Exception as e:
        print(f"Error parsing datetime: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("Current Time")
        parse_and_convert(
            str(int(datetime.now(pytz.UTC).timestamp())),
            show_relative=False,
            quiet=True,
        )
    else:
        parse_and_convert(" ".join(sys.argv[1:]))
