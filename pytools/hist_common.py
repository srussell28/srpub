#!/usr/bin/env python3

import argparse
import operator
import time

from colorstrings import grey_str
from srutils import flushprint, quick_ingest_line

# |sort | uniq -c | sort -nr


gcom = grey_str(",")


def _print_hist(
    seen,
    total_cnt,
    t0,
    lim,
    with_rate=True,
    alphabetical=False,
    dups_only=False,
    with_perc=True,
    last=False,
):
    if alphabetical:
        sortseen = sorted(seen.items(), key=operator.itemgetter(0), reverse=False)
    else:
        sortseen = sorted(seen.items(), key=operator.itemgetter(1), reverse=True)

    lines = []
    line = (
        f"--------------------------------- {len(sortseen)} unique, {total_cnt} total"
    )
    if with_rate:
        overall_rate = total_cnt / (time.time() - t0)
        line += f", {overall_rate:.1f}/s"
    lines.append(line)
    if with_rate and with_perc:
        lines.append("  cnt      %     rate  thing")
        lines.append("  ---    ----    ----  -----")
    elif with_rate:
        lines.append("  cnt    rate   thing")
        lines.append("  ---    ----   -----")
    elif with_perc:
        lines.append("  cnt      %    thing")
        lines.append("  ---    ----   -----")
    else:
        lines.append("  cnt  thing")
        lines.append("  ---  -----")
    tdelt = time.time() - t0
    for x in sortseen[0:lim]:
        tot = int(x[1])
        if dups_only and tot == 1:
            continue
        rate = tot / tdelt
        perc = 100.0 * tot / total_cnt
        if with_rate and with_perc:
            lines.append(
                f"{int(tot):5} {gcom}{perc:5.1f} {gcom} {rate:5.1f} {gcom} {x[0]}"
            )
        elif with_rate:
            lines.append(f"{int(tot):5} {gcom} {rate:5.1f} {gcom} {x[0]}")
        elif with_perc:
            lines.append(f"{int(tot):5} {gcom} {perc:5.1f} {gcom} {x[0]}")
        else:
            lines.append(f"{int(tot):5} {gcom} {x[0]}")
    lines.append("")

    if last:
        for line in lines:
            print(line)
    else:
        flushprint(lines)


def main():
    parser = argparse.ArgumentParser("histogram common lines from file or stdin")
    parser.add_argument(
        "--alphabetical",
        action="store_true",
        help="sort alphabetically, not by frequency",
    )
    parser.add_argument("--interval", type=int, default=3, help="refresh interval")
    parser.add_argument("--no-percent", action="store_true", help="dont show percent")
    parser.add_argument("--no-rate", action="store_false", help="dont show the rate")
    parser.add_argument(
        "--duplicates", action="store_true", help="only show duplicates"
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="number of entries to show"
    )
    parser.add_argument(
        "--all", action="store_true", help="show all values (overrides limit)"
    )

    args = parser.parse_args()
    _main(args)


def _main(args):
    limit = 10000000 if args.all else args.limit
    seen = dict()
    total_cnt = 0
    lprint = time.time()
    t0 = time.time()
    printed = False

    try:
        for line in quick_ingest_line():
            line = line.rstrip().lstrip()
            seen[line] = seen.get(line, 0) + 1
            total_cnt += 1
            if time.time() - lprint > args.interval:
                lprint = time.time()
                printed = True
                _print_hist(
                    seen,
                    total_cnt,
                    t0,
                    limit,
                    alphabetical=args.alphabetical,
                    dups_only=args.duplicates,
                    with_perc=(not args.no_percent),
                    last=False,
                )
    except KeyboardInterrupt:
        pass
    finally:
        if printed:
            # Clear the flush-printed lines
            print("\n" * (args.limit + 10))
            print("\nSTDOUT terminated\n\n\n")
        _print_hist(
            seen,
            total_cnt,
            t0,
            limit,
            with_rate=(time.time() - t0 >= args.interval) and not args.no_rate,
            alphabetical=args.alphabetical,
            dups_only=args.duplicates,
            with_perc=(not args.no_percent),
            last=True,
        )


if __name__ == "__main__":
    main()
