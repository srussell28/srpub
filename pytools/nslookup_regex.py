#!/usr/bin/env python3

import os
import re
import socket
import sys

import colorstrings
from srutils import cmd, load_pickle, save_pickle

IGNORE_LIST = ["Administered by ARIN"]


def whois_query(q):
    resp = cmd(f"whois {q}")
    result = ""
    d = dict()
    for line in resp.split("\n"):
        line = line.strip()
        m = re.search(r"^(.*?)\:(.*?)$", line)
        if m:
            key = m.group(1).lower()
            d[key] = d.get(key, "") + m.group(2).strip()
    result = ""
    for k in ["organisation", "org-name", "city", "stateprov", "country"]:
        if k in d:
            v = d.get(k, "")
            if v in IGNORE_LIST:
                continue
            result += v + ", "
    return result


whoiscache_path = os.path.join(os.getenv("HOME"), ".cache/whois.pkl")
whoiscache = load_pickle(whoiscache_path, dict())


def whois_lookup(ip):
    global whoiscache
    if ip in whoiscache:
        return whoiscache[ip]
    try:
        resp = whois_query(ip)
    except Exception:
        whoiscache[ip] = None
        raise
        return None
    whoiscache[ip] = resp
    return resp


nscache_path = os.path.join(os.getenv("HOME"), ".cache/nslookup.pkl")
nscache = load_pickle(nscache_path, dict())


def ns_lookup(ip):
    global nscache
    if ip in nscache:
        return nscache[ip]
    try:
        fullhost = socket.gethostbyaddr(ip)[0]
    except Exception:
        nscache[ip] = None
        return None
    res = fullhost
    nscache[ip] = res
    return res


aux_lookup_dat = None
aux_lookup_file = os.getenv("NSLOOKUP_AUX")
if aux_lookup_file:
    with open(aux_lookup_file, "r") as f:
        aux_lookup_dat = list(f.readlines())


def aux_lookup(ip):
    if not aux_lookup_dat:
        return None
    # only return back if we match 1 line
    matching_lines = [line for line in aux_lookup_dat if ip in line]
    if len(matching_lines) == 1:
        return matching_lines[0]


def lookup_ip(ip):
    if aux := aux_lookup(ip):
        return aux
    dns = ns_lookup(ip)
    whois = whois_lookup(ip)
    if dns and whois:
        return f"{dns} : {whois}"
    if dns:
        return dns
    if whois:
        return whois


def save_caches():
    global nscache
    global whoiscache
    save_pickle(whoiscache, whoiscache_path)
    save_pickle(nscache, nscache_path)


if __name__ == "__main__":
    for line in sys.stdin:
        hexids = list(re.findall(r"[0-9A-Fa-f]{10}", line))
        ips = list(re.findall(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", line))
        for hexid in hexids:
            line = line.replace(hexid, colorstrings.red_str(hexid))
            lookup = aux_lookup(hexid)
            if lookup:
                line = line.rstrip() + " " + colorstrings.blue_str(lookup.rstrip())
        for ip in ips:
            lookup = lookup_ip(ip)
            if lookup:
                comb = (
                    colorstrings.green_str(ip)
                    + " : "
                    + colorstrings.blue_str(lookup.rstrip())
                )
                line = line.replace(ip, comb, 1)
            else:
                line = line.replace(ip, colorstrings.green_str(ip), 1)
        print(line.rstrip())
    save_caches()
