#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ============================================================
# CONFIG
# ============================================================

BASE_OUT = (
    Path("/Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic")
    / "Reports"
)

TR_STATE_PATH = Path(
    os.environ.get(
        "TR_STATE_PATH",
        str(
            Path.home()
            / "Library"
            / "Application Support"
            / "Finanzen"
            / "TR_CASH"
            / "tr_state.json"
        ),
    )
)

STATE_PATH = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Finanzen"
    / "global_finance_state.json"
)


MONTHS = {
    "jan": 1,
    "jan.": 1,
    "feb": 2,
    "feb.": 2,
    "mär": 3,
    "mär.": 3,
    "märz": 3,
    "mrz": 3,
    "mrz.": 3,
    "apr": 4,
    "apr.": 4,
    "mai": 5,
    "jun": 6,
    "jun.": 6,
    "jul": 7,
    "jul.": 7,
    "aug": 8,
    "aug.": 8,
    "sep": 9,
    "sep.": 9,
    "okt": 10,
    "okt.": 10,
    "nov": 11,
    "nov.": 11,
    "dez": 12,
    "dez.": 12,
}


LEDGER_COLUMNS = [
    "id",
    "booking_date",
    "typ",
    "beschreibung",
    "in_eur",
    "out_eur",
    "net_eur",
    "saldo_eur",
    "ingested_at",
]

# ============================================================
# Minimal logging (stdout only; captured by cash-run tee)
# Keep this tiny: only agreed RUN start/end + key results.
# ============================================================


def _ts() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def log(tag: str, msg: str) -> None:
    print(f"[{_ts()}] [{tag}] {msg}")


def log_run_start() -> None:
    log("S2R", "start tr_reports_from_tr_state")


def log_run_end(result: str) -> None:
    log("S2R", f"end | result={result}")


def now_iso_local() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def write_json_atomic(p: Path, data: Dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def write_csv_atomic(path: Path, header: List[str], rows: List[List[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)
    tmp.replace(path)


def de_money_to_float(s: str) -> float:
    s = (s or "").strip()
    if not s:
        return 0.0
    s = s.replace("€", "").replace("EUR", "").replace(" ", "").replace("+", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def fmt_de(n: float) -> str:
    return f"{n:.2f}".replace(".", ",")


def parse_tr_date(s: str) -> str:
    s = (s or "").strip()
    m = re.match(r"^(\d{1,2})\s+([A-Za-zÄÖÜäöü\.]+)\s+(\d{4})$", s)
    if not m:
        return ""

    day = int(m.group(1))
    mon_raw = m.group(2).strip().lower()
    year = int(m.group(3))

    mk = mon_raw
    if mk not in MONTHS:
        mk = mk.replace(".", "")
    month = MONTHS.get(mk, 0)

    if not month:
        mk2 = mk.replace("ä", "a").replace("ö", "o").replace("ü", "u")
        month = MONTHS.get(mk2, 0)

    if not month:
        return ""

    try:
        dt = datetime(year, month, day)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def year_of(ymd: str) -> int:
    if re.match(r"^\d{4}-\d{2}-\d{2}$", (ymd or "")):
        return int(ymd[:4])
    return 1900


def month_key(ymd: str) -> str:
    if re.match(r"^\d{4}-\d{2}-\d{2}$", (ymd or "")):
        return ymd[:7]
    return "1900-01"


def ymd_key(ymd: str) -> Tuple[int, int, int]:
    ymd = (ymd or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", ymd):
        return (0, 0, 0)
    try:
        dt = datetime.strptime(ymd, "%Y-%m-%d")
        return (dt.year, dt.month, dt.day)
    except Exception:
        return (0, 0, 0)


# ============================================================
# Helper: max booking date from items
# ============================================================

def max_booking_date_from_items(items: List[Dict[str, Any]]) -> str:
    """Return max booking date (YYYY-MM-DD) across given TR items; '' if none."""
    best = ""
    best_k = (0, 0, 0)
    for it in items:
        d = parse_tr_date(str(it.get("datum", "")))
        k = ymd_key(d)
        if k > best_k:
            best_k = k
            best = d
    return best



# ============================================================
# Year helpers for reporting (args-driven)
# ============================================================


def parse_year_args(argv: List[str]) -> List[int]:
    years: List[int] = []
    for a in argv:
        a = (a or "").strip()
        if re.fullmatch(r"\d{4}", a):
            years.append(int(a))
    years = sorted(set(years))
    return years


def filter_items_to_years(items: List[Dict[str, Any]], years: List[int]) -> List[Dict[str, Any]]:
    if not years:
        return items
    ys = set(years)
    out: List[Dict[str, Any]] = []
    for it in items:
        d = parse_tr_date(str(it.get("datum", "")))
        if not d:
            continue
        if year_of(d) in ys:
            out.append(it)
    return out


def summarize_years_for_log(years: List[int], rows_count: int) -> str:
    if not years:
        return f"reports_updated | years=? rows={rows_count}"
    if len(years) == 1:
        return f"report_updated | year={years[0]} rows={rows_count}"
    return f"reports_updated | years={years[0]}-{years[-1]} rows={rows_count}"


# ============================================================
# Global global_finance_state.json (atomic)
# ============================================================


def ensure_global_exists() -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if STATE_PATH.exists():
        return

    payload = {
        "updatedAt": "",
        "accounts": {
            "N26": {"value": 0.0, "currency": "EUR", "asOfDate": "", "updatedAt": ""},
            "TR_Cash": {
                "value": 0.0,
                "currency": "EUR",
                "asOfDate": "",
                "updatedAt": "",
            },
            "TR_Invested": {
                "value": 0.0,
                "currency": "EUR",
                "asOfDate": "",
                "updatedAt": "",
            },
            "ZERO": {"value": 0.0, "currency": "EUR", "asOfDate": "", "updatedAt": ""},
            "IG": {"value": 0.0, "currency": "EUR", "asOfDate": "", "updatedAt": ""},
            "BAR": {"value": 0.0, "currency": "EUR", "asOfDate": "", "updatedAt": ""},
        },
    }
    write_json_atomic(STATE_PATH, payload)


def update_state_account(
    key: str, value: float, as_of_date: str, ingested_at: str
) -> bool:
    ensure_global_exists()
    try:
        data = read_json(STATE_PATH)
    except Exception:
        data = {"updatedAt": "", "accounts": {}}

    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        accounts = {}
        data["accounts"] = accounts

    acc = accounts.get(key)
    if not isinstance(acc, dict):
        acc = {"value": 0.0, "currency": "EUR", "asOfDate": "", "updatedAt": ""}

    existing_asof = (acc.get("asOfDate") or "").strip()
    existing_upd = (acc.get("updatedAt") or "").strip()

    new_asof = (as_of_date or "").strip()
    new_upd = (ingested_at or "").strip() or now_iso_local()

    ex_asof_k = ymd_key(existing_asof)
    nw_asof_k = ymd_key(new_asof)

    if ex_asof_k != (0, 0, 0) and nw_asof_k != (0, 0, 0):
        if nw_asof_k < ex_asof_k:
            return False
        if nw_asof_k == ex_asof_k:
            if existing_upd and new_upd <= existing_upd:
                return False

    if ex_asof_k != (0, 0, 0) and nw_asof_k == (0, 0, 0):
        return False

    acc["value"] = round(float(value), 2)
    acc["currency"] = acc.get("currency", "EUR")
    acc["asOfDate"] = new_asof
    acc["updatedAt"] = new_upd

    accounts[key] = acc
    data["updatedAt"] = new_upd

    write_json_atomic(STATE_PATH, data)
    return True


# ============================================================
# Paths / Reports
# ============================================================


def konto_paths(year: int):
    root = BASE_OUT / str(year)
    ledger_dir = root / "Ledger"
    month_dir = root / "Monatsübersichten"
    ytd_dir = root / "Jahresübersicht"
    ledger_csv = ledger_dir / "TR_Cash_Ledger.csv"
    return root, ledger_dir, month_dir, ytd_dir, ledger_csv


def ensure_dirs_for_year(year: int) -> None:
    _, ledger_dir, month_dir, ytd_dir, _ = konto_paths(year)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    month_dir.mkdir(parents=True, exist_ok=True)
    ytd_dir.mkdir(parents=True, exist_ok=True)


def row_id(row: Dict[str, str]) -> str:
    key = "|".join(
        [
            row.get("booking_date", ""),
            row.get("typ", ""),
            row.get("beschreibung", ""),
            row.get("in_eur", ""),
            row.get("out_eur", ""),
            row.get("saldo_eur", ""),
        ]
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def write_month_csv(month_dir: Path, month: str, rows: List[Dict[str, str]]) -> None:
    out = month_dir / f"TR_Cash_{month}.csv"
    hdr = ["Datum", "Typ", "Beschreibung", "Eingang", "Ausgang", "Netto", "Saldo"]
    rr: List[List[str]] = [
        [
            r["booking_date"],
            r["typ"],
            r["beschreibung"],
            r["in_eur"],
            r["out_eur"],
            r["net_eur"],
            r["saldo_eur"],
        ]
        for r in rows
    ]
    write_csv_atomic(out, hdr, rr)


def write_ytd_csv(
    ytd_dir: Path, year: int, month_rows: Dict[str, List[Dict[str, str]]]
) -> None:
    out = ytd_dir / f"TR_Cash_YTD_{year}.csv"
    months = sorted([m for m in month_rows.keys() if m.startswith(f"{year}-")])
    hdr = ["Monat", "Eingang", "Ausgang", "Netto", "Letzter_Saldo"]

    rr: List[List[str]] = []
    for m in months:
        ins = sum(de_money_to_float(x["in_eur"]) for x in month_rows[m])
        outs = sum(de_money_to_float(x["out_eur"]) for x in month_rows[m])
        net = sum(de_money_to_float(x["net_eur"]) for x in month_rows[m])
        last_saldo = month_rows[m][-1]["saldo_eur"] if month_rows[m] else "0,00"
        rr.append([m, fmt_de(ins), fmt_de(outs), fmt_de(net), last_saldo])

    write_csv_atomic(out, hdr, rr)


# ============================================================
# Core
# ============================================================


def load_tr_state() -> Dict[str, Any]:
    if not TR_STATE_PATH.exists():
        return {}
    try:
        return read_json(TR_STATE_PATH)
    except Exception:
        return {}


def iter_state_tx_items_in_state_order(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    tx = state.get("tx", {}) if isinstance(state, dict) else {}
    if not isinstance(tx, dict):
        return []

    out: List[Dict[str, Any]] = []
    for _, v in tx.items():  # insertion-order
        if isinstance(v, dict):
            out.append(v)
    return out


def compute_current_balance_from_items(
    items: List[Dict[str, Any]],
) -> Tuple[float, str]:
    if not items:
        return 0.0, ""

    last = items[-1]
    bal = de_money_to_float(str(last.get("saldo", "")))
    asof = parse_tr_date(str(last.get("datum", "")))
    return bal, asof


def update_tr_state_stats(
    state: Dict[str, Any], items: List[Dict[str, Any]]
) -> Tuple[float, str]:
    cur_bal, cur_asof = compute_current_balance_from_items(items)

    stats = state.setdefault("stats", {})
    stats["currentBalance"] = round(float(cur_bal), 2)
    stats["currentBalanceAsOfDate"] = (cur_asof or "").strip()

    state["updatedAt"] = now_iso_local()
    write_json_atomic(TR_STATE_PATH, state)

    return cur_bal, cur_asof


def build_rows_by_year_from_state(
    items: List[Dict[str, Any]], ingested_at: str
) -> Dict[int, List[Dict[str, str]]]:
    by_year: Dict[int, List[Dict[str, str]]] = {}

    for it in items:
        d = parse_tr_date(it.get("datum", ""))
        if not d:
            continue

        y = year_of(d)

        typ = (it.get("typ") or "").strip()
        besch = (it.get("beschreibung") or "").strip()

        ein = de_money_to_float(it.get("zahlungseingang", ""))
        aus = de_money_to_float(it.get("zahlungsausgang", ""))
        net = ein - aus
        saldo = de_money_to_float(it.get("saldo", ""))

        row = {
            "booking_date": d,
            "typ": typ,
            "beschreibung": besch,
            "in_eur": fmt_de(ein),
            "out_eur": fmt_de(aus),
            "net_eur": fmt_de(net),
            "saldo_eur": fmt_de(saldo),
            "ingested_at": ingested_at,
        }
        row["id"] = row_id(row)

        by_year.setdefault(y, []).append(row)  # STATE ORDER preserved

    return by_year


def write_ledger_and_reports(by_year: Dict[int, List[Dict[str, str]]]) -> None:
    for y, rows in sorted(by_year.items()):
        ensure_dirs_for_year(y)
        _, _, month_dir, ytd_dir, ledger_csv = konto_paths(y)

        # Ledger: overwrite, state-order
        ledger_rows: List[List[str]] = [
            [
                r["id"],
                r["booking_date"],
                r["typ"],
                r["beschreibung"],
                r["in_eur"],
                r["out_eur"],
                r["net_eur"],
                r["saldo_eur"],
                r["ingested_at"],
            ]
            for r in rows
        ]
        write_csv_atomic(ledger_csv, LEDGER_COLUMNS, ledger_rows)

        # Month reports: also state-order (within month)
        by_month: Dict[str, List[Dict[str, str]]] = {}
        for r in rows:
            m = month_key(r["booking_date"])
            by_month.setdefault(m, []).append(r)

        for m, rws in by_month.items():
            write_month_csv(month_dir, m, rws)

        write_ytd_csv(ytd_dir, y, by_month)


def main() -> None:
    log_run_start()
    # log("INFO", f"TR_STATE_PATH: {TR_STATE_PATH}")
    # log("INFO", f"BASE_OUT: {BASE_OUT}")
    BASE_OUT.mkdir(parents=True, exist_ok=True)

    state = load_tr_state()
    items_all = iter_state_tx_items_in_state_order(state)
    log("S2R", f"tx_count: {len(items_all)}")

    if not items_all:
        log("S2R", "no tx items")
        log_run_end("noop")
        return

    ingested_at = now_iso_local()

    # 1) stats.currentBalance + stats.currentBalanceAsOfDate in tr_state.json
    #    (für Global-Push)
    cur_bal, cur_asof = update_tr_state_stats(state, items_all)

    # 2) Reports nur für die Jahre, die als Args übergeben werden
    target_years = parse_year_args(sys.argv[1:])
    if target_years:
        log("S2R", f"target_years: {','.join(str(y) for y in target_years)}")

    items = filter_items_to_years(items_all, target_years)

    if not items:
        if target_years:
            log("S2R", f"no items in target_years | years={','.join(str(y) for y in target_years)}")
        else:
            log("S2R", "no items (no year args)")
        log_run_end("noop")
        return

    by_year_full = build_rows_by_year_from_state(items, ingested_at)

    # Schreibe nur die betroffenen Jahre
    years_written = sorted(by_year_full.keys())
    total_rows = sum(len(v) for v in by_year_full.values())

    # Log: ein Jahr vs. mehrere Jahre
    log("S2R", summarize_years_for_log(years_written, total_rows))

    write_ledger_and_reports(by_year_full)
    if len(years_written) == 1:
        log("S2R", f"reports written | year={years_written[0]}")
    else:
        log("S2R", f"reports written | years={','.join(str(y) for y in years_written)}")

    # 3) push to global
    #    If we are re-reporting an older period (max booking date of the report items
    #    is older than stats.currentBalanceAsOfDate), skip global update entirely.
    max_bd = max_booking_date_from_items(items)
    if cur_asof and max_bd and ymd_key(max_bd) < ymd_key(cur_asof):
        log(
            "S2R",
            f"global skip | maxBookingDate={max_bd} < currentBalanceAsOfDate={cur_asof}",
        )
    elif cur_asof:
        changed = update_state_account("TR_Cash", cur_bal, cur_asof, ingested_at)
        if changed:
            log(
                "S2R",
                f"global updated | asOf={cur_asof} value={round(float(cur_bal),2):.2f}",
            )
        else:
            log("WARN", "global not updated | older_or_equal_asOf")
    else:
        log("WARN", "global not updated | missing asOf")

    log_run_end("ok")


if __name__ == "__main__":
    main()
