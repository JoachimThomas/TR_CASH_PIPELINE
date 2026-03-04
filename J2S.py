#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import hashlib
import argparse
from pathlib import Path
from datetime import datetime, date
import re
import sys

STATE_PATH = (
    Path.home()
    / "Library/Application Support/Finanzen/TR_CASH/tr_state.json"
)

RC_OK = 0
RC_SKIP = 10

REQUIRED = [
    "datum",
    "typ",
    "beschreibung",
    "zahlungseingang",
    "zahlungsausgang",
    "saldo",
]

DATE_RE = re.compile(r"(\d{2})\s+([A-Za-zäöüÄÖÜ\.]+)\s+(\d{4})")

MONTHS = {
    "jan":1,"feb":2,"mär":3,"apr":4,"mai":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"okt":10,"nov":11,"dez":12
}

# ---------------------------------------------------------

def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(msg):
    print(f"[{ts()}] J2S | {msg}")

# ---------------------------------------------------------

def parse_date(d):
    m = DATE_RE.search(d or "")
    if not m:
        return ""
    dd, mm, yy = m.groups()
    mm = mm.lower().strip(".")[:3]
    if mm not in MONTHS:
        return ""
    return f"{yy}-{MONTHS[mm]:02d}-{dd}"

def uid(rec):
    key = "|".join(str(rec.get(k,"")) for k in REQUIRED)
    return hashlib.sha1(key.encode()).hexdigest()[:16]

def saldo_valid(s):
    s = (s or "").strip()
    return s not in ("", "0", "0,00 €")

# ---------------------------------------------------------

def load_state():
    if not STATE_PATH.exists():
        return {"tx":{}, "stats":{}}
    return json.loads(STATE_PATH.read_text())

def save_state(s):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(s,indent=2,ensure_ascii=False))

# ---------------------------------------------------------

def compute_stats(tx):
    dates=[]
    balances=[]
    for r in tx.values():
        d=parse_date(r["datum"])
        if d:
            dates.append(d)
            balances.append((d,r["saldo"]))
    if not dates:
        return {}
    dates.sort()
    balances.sort()
    return {
        "txCount": len(tx),
        "minBookingDate": dates[0],
        "maxBookingDate": dates[-1],
        "currentBalance": balances[-1][1],
        "currentBalanceAsOfDate": balances[-1][0],
        "lastPeriodFrom": dates[0],
        "lastPeriodTo": dates[-1],
    }

# ---------------------------------------------------------

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("json_path")
    args=ap.parse_args()

    src=Path(args.json_path)
    if not src.exists():
        log("json not found -> skipped")
        return RC_SKIP

    log("start")

    data=json.loads(src.read_text())
    if not isinstance(data,list):
        log("json empty -> skipped")
        return RC_SKIP

    state=load_state()
    tx=state.setdefault("tx",{})

    new=0
    min_d,max_d="",""

    for r in data:
        if not all(k in r for k in REQUIRED):
            continue

        if not saldo_valid(r.get("saldo")):
            continue

        i=uid(r)
        if i in tx:
            continue

        tx[i]=r
        new+=1

        d=parse_date(r["datum"])
        if d:
            if not min_d or d<min_d: min_d=d
            if not max_d or d>max_d: max_d=d

    if new==0:
        log("no new tx -> skipped")
        return RC_SKIP

    state["stats"]=compute_stats(tx)

    save_state(state)

    log(f"ingested={new} period={min_d}_bis_{max_d}")
    log("end | result=updated")
    return RC_OK

# ---------------------------------------------------------

if __name__=="__main__":
    sys.exit(main())