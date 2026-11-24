#!/usr/bin/env python3

import os
import sys

DB_DIR = os.environ.get(
    "GEOIP_DB_DIR", os.path.expanduser("~/misc/GeoLite2-City-CSV_20190813/")
)
IP_PATH = DB_DIR + "GeoLite2-City-Blocks-IPv4.csv"
CITY_PATH = DB_DIR + "GeoLite2-City-Locations-en.csv"


def truncate(ip, n=3):
    return ".".join(ip.split(".")[0:n])


def load_db():
    print("Loading ip DB")
    res = {}
    with open(IP_PATH, "rb") as f:
        for line in f:
            parts = line.split(",")
            ip_sub = parts[0]
            ip = ip_sub.split("/")[0]
            city_code = parts[1]
            lat = parts[7]
            lng = parts[8]
            # print(ip, lat, lng)
            res[truncate(ip, 3)] = (city_code, lat, lng)
            res[truncate(ip, 2)] = (city_code, lat, lng)
    return res


_ipdb = None


def get_ip_location(ip):
    global _ipdb
    if _ipdb is None:
        _ipdb = load_db()
    res = _ipdb.get(truncate(ip, 3), None)
    if res:
        return res
    return _ipdb.get(truncate(ip, 2), None)


if __name__ == "__main__":
    print(get_ip_location(sys.argv[1]))
