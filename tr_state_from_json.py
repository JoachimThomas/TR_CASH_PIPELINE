#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import hashlib
import re
import argparse
import os
from pathlib import Path
from datetime import datetime, timezone, date
from typing import Dict, Any, List, Optional

# ============================================================
# CONFIG
# ============================================================

STATE_PATH = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Finanzen"
    / "TR_CASH"
    / "tr_state.json"
)
# Fallback-Suchpfad (Legacy): wenn kein JSON-Pfad als Arg übergeben wird.
# Neu: Standard ist die TR-Cash-INBOX, nicht Downloads.
TR_BASE_DIR = Path(
    os.environ.get(
        "TR_CASH_INBOX_JSON",
        "/Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/INBOX_CASH_JSON",
    )
)

REQUIRED_KEYS = [
    "datum",
    "typ",
    "beschreibung",
    "zahlungseingang",
    "zahlungsausgang",
    "saldo",
]

MONTHS_DE = {
    "jan": 1,
    "jan.": 1,
    "januar": 1,
    "feb": 2,
    "feb.": 2,
    "februar": 2,
    "mär": 3,
    "mär.": 3,
    "maerz": 3,
    "märz": 3,
    "apr": 4,
    "apr.": 4,
    "april": 4,
    "mai": 5,
    "jun": 6,
    "jun.": 6,
    "juni": 6,
    "jul": 7,
    "jul.": 7,
    "juli": 7,
    "aug": 8,
    "aug.": 8,
    "august": 8,
    "sep": 9,
    "sep.": 9,
    "september": 9,
    "okt": 10,
    "okt.": 10,
    "oktober": 10,
    "nov": 11,
    "nov.": 11,
    "november": 11,
    "dez": 12,
    "dez.": 12,
    "dezember": 12,
}
DATE_RE = re.compile(r"^\s*(\d{2})\s+([A-Za-zÄÖÜäöüß\.]+)\s+(\d{4})\s*$")

SCHEMA_VERSION = 1
RC_OK = 0
RC_SKIP_ALREADY = 10
RC_FAIL = 2

# ============================================================
# Minimal logging (stdout only; picked up by calling shell tee)
# Keep this tiny: only agreed RUN start/end + key results.
# ============================================================


def _ts() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _log(tag: str, msg: str) -> None:
    print(f"[{_ts()}] [{tag}] {msg}")


def log_run_start() -> None:
    _log("J2S", "start tr_state_from_json")


def log_run_end(result: str) -> None:
    _log("J2S", f"end | result={result}")


# ============================================================
# Helpers
# ============================================================


def now_iso_local() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha1_hex(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def sha1_file_full(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_tr_datum_to_ymd(datum: str) -> str:
    s = (datum or "").strip()
    m = DATE_RE.match(s)
    if not m:
        return ""
    dd = int(m.group(1))
    mon_raw = (m.group(2) or "").strip().lower()
    yyyy = int(m.group(3))

    mon_raw = mon_raw.replace("märz", "mär").replace("maerz", "mär")
    mm = MONTHS_DE.get(mon_raw) or MONTHS_DE.get(mon_raw.rstrip("."))
    if not mm:
        return ""
    try:
        dt = datetime(yyyy, mm, dd)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _parse_iso_date(s: str) -> date | None:
    try:
        if not s:
            return None
        return date.fromisoformat(str(s).strip()[0:10])
    except Exception:
        return None


def _pick_latest_source_period(sources: dict) -> tuple[str, str]:
    """Return (from,to) of the most recently ingested source (by ingestedAt)."""
    if not isinstance(sources, dict) or not sources:
        return "", ""

    best_from, best_to = "", ""
    best_ts = ""

    for v in sources.values():
        if not isinstance(v, dict):
            continue
        ts = str(v.get("ingestedAt") or "")
        if ts and (not best_ts or ts > best_ts):
            best_ts = ts
            p = v.get("period") or {}
            best_from = str(p.get("from") or "")
            best_to = str(p.get("to") or "")

    return best_from, best_to


def _pick_current_balance_from_tx(tx: dict) -> tuple[str, str]:
    """Pick current balance from the tx whose booking date is closest to today.

    Prefer the latest booking date <= today; if none, take the latest available booking date.
    Returns (balance_str, asof_ymd).
    """
    if not isinstance(tx, dict) or not tx:
        return "", ""

    today = date.today()

    best_before = None  # tuple(date, balance_str)
    best_any = None  # tuple(date, balance_str)

    for r in tx.values():
        if not isinstance(r, dict):
            continue
        ymd = parse_tr_datum_to_ymd(_safe_str(r.get("datum")))
        d = _parse_iso_date(ymd)
        if not d:
            continue
        bal = _safe_str(r.get("saldo"))

        if (best_any is None) or (d > best_any[0]):
            best_any = (d, bal)

        if d <= today:
            if (best_before is None) or (d > best_before[0]):
                best_before = (d, bal)

    pick = best_before or best_any
    if not pick:
        return "", ""

    return pick[1], pick[0].isoformat()


def find_latest_json(base_dir: Path) -> Optional[Path]:
    if not base_dir.exists():
        return None
    best: Optional[Path] = None
    best_mtime = -1.0
    for p in base_dir.rglob("*.json"):
        try:
            if not p.is_file():
                continue
            mt = p.stat().st_mtime
            if mt > best_mtime:
                best_mtime = mt
                best = p
        except Exception:
            continue
    return best


def _safe_str(x: Any) -> str:
    return "" if x is None else str(x)


# ============================================================
# State I/O
# ============================================================


def ensure_state_exists():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if STATE_PATH.exists():
        return
    payload = {
        "schema": SCHEMA_VERSION,
        "updatedAt": "",
        "meta": {
            "lastImport": {
                "sourceFile": "",
                "sourcePath": "",
                "sourceUid": "",
                "sourceHash": "",
                "importedAt": "",
                "period": {"from": "", "to": ""},
            }
        },
        "sources": {},
        "stats": {
            "txCount": 0,
            "minBookingDate": "",
            "maxBookingDate": "",
            "currentBalance": "",
            "currentBalanceAsOfDate": "",
            "lastPeriodFrom": "",
            "lastPeriodTo": "",
        },
        "tx": {},
    }
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def load_state() -> Dict[str, Any]:
    ensure_state_exists()

    try:
        raw = STATE_PATH.read_text(encoding="utf-8")
        state = json.loads(raw) if raw.strip() else {}
    except Exception:
        state = {}

    if not isinstance(state, dict):
        state = {}

    state.setdefault("schema", SCHEMA_VERSION)
    state.setdefault("updatedAt", "")
    state.setdefault("meta", {})
    state["meta"].setdefault(
        "lastImport",
        {
            "sourceFile": "",
            "sourcePath": "",
            "sourceUid": "",
            "sourceHash": "",
            "importedAt": "",
            "period": {"from": "", "to": ""},
        },
    )
    state.setdefault("sources", {})
    state.setdefault(
        "stats",
        {
            "txCount": 0,
            "minBookingDate": "",
            "maxBookingDate": "",
            "currentBalance": "",
            "currentBalanceAsOfDate": "",
            "lastPeriodFrom": "",
            "lastPeriodTo": "",
        },
    )
    state.setdefault("tx", {})

    if not isinstance(state["sources"], dict):
        state["sources"] = {}
    if not isinstance(state["tx"], dict):
        state["tx"] = {}

    return state


def save_state(state: Dict[str, Any]):
    state["updatedAt"] = now_iso_local()
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


# ============================================================
# Core logic: tx + stats + ids
# ============================================================


def record_core_equal(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    for k in REQUIRED_KEYS:
        if _safe_str(a.get(k)) != _safe_str(b.get(k)):
            return False
    return True


def update_stats(state: Dict[str, Any]):
    tx = state.get("tx", {}) or {}
    dates: List[str] = []

    for r in tx.values():
        if not isinstance(r, dict):
            continue
        ymd = parse_tr_datum_to_ymd(_safe_str(r.get("datum")))
        if ymd:
            dates.append(ymd)

    stats = state.setdefault("stats", {})
    stats["txCount"] = len(tx)

    if dates:
        stats["minBookingDate"] = min(dates)
        stats["maxBookingDate"] = max(dates)
    else:
        stats["minBookingDate"] = ""
        stats["maxBookingDate"] = ""

    # Current balance: derive from the tx booking date closest to today (prefer <= today)
    bal, asof = _pick_current_balance_from_tx(tx)
    stats["currentBalance"] = bal
    stats["currentBalanceAsOfDate"] = asof

    # Last import period: derive from newest entry in sources (by ingestedAt)
    src_from, src_to = _pick_latest_source_period(state.get("sources", {}) or {})
    stats["lastPeriodFrom"] = src_from
    stats["lastPeriodTo"] = src_to


def make_base_id(rec: Dict[str, Any]) -> str:
    key = "|".join([_safe_str(rec.get(k)) for k in REQUIRED_KEYS])
    return sha1_hex(key)[:16]


def make_dup_id(rec: Dict[str, Any], source_uid: str, rownum: int) -> str:
    key = "|".join([_safe_str(rec.get(k)) for k in REQUIRED_KEYS])
    return sha1_hex(f"{key}|dup|{source_uid}:{rownum}")[:16]


# ============================================================
# Input normalize
# ============================================================


def normalize_input_json(obj: Any) -> List[Dict[str, Any]]:
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        for k in ("tx", "data", "items", "rows"):
            v = obj.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        if all(k in obj for k in REQUIRED_KEYS):
            return [obj]
    return []


def is_tr_row(row: Dict[str, Any]) -> bool:
    return all(k in row for k in REQUIRED_KEYS)


# ============================================================
# Dedupe rule: source already processed?
# ============================================================


def source_already_ingested(state: Dict[str, Any], source_uid: str) -> bool:
    sources = state.get("sources", {}) or {}
    tx = state.get("tx", {}) or {}

    # FAILSAFE: wenn State faktisch leer ist -> niemals "already"
    if isinstance(sources, dict) and isinstance(tx, dict):
        if len(sources) == 0 and len(tx) == 0:
            return False

    if not isinstance(sources, dict):
        return False
    return source_uid in sources


# ============================================================
# Ingest
# ============================================================


def ingest_json(
    path: Path,
    state: Dict[str, Any],
    source_file: str,
    imported_at: str,
    period_from: str,
    period_to: str,
) -> Dict[str, Any]:

    added = 0
    skipped = 0
    dups = 0
    bad = 0

    source_hash = sha1_file_full(path)
    source_uid = source_hash[:16]

    if source_already_ingested(state, source_uid):
        return {
            "status": "skipped_already_ingested",
            "added": 0,
            "dups": 0,
            "skipped": 0,
            "bad": 0,
            "source_uid": source_uid,
            "source_hash": source_hash,
        }

    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = normalize_input_json(raw)

    tx = state.setdefault("tx", {})
    for rownum, row in enumerate(rows, start=1):
        try:
            if not isinstance(row, dict) or not is_tr_row(row):
                bad += 1
                continue

            rec = {
                k: (row.get(k) if row.get(k) is not None else "") for k in REQUIRED_KEYS
            }
            rec["ingestedAt"] = imported_at
            rec["sourceUid"] = source_uid
            rec["sourceFile"] = source_file

            base_id = make_base_id(rec)

            if base_id not in tx:
                tx[base_id] = rec
                added += 1
                continue

            existing = tx.get(base_id) or {}
            if isinstance(existing, dict) and record_core_equal(existing, rec):
                skipped += 1
                continue

            dup_id = make_dup_id(rec, source_uid, rownum)
            if dup_id in tx:
                skipped += 1
                continue

            tx[dup_id] = rec
            dups += 1

        except Exception:
            bad += 1

    sources = state.setdefault("sources", {})
    sources[source_uid] = {
        "uid": source_uid,
        "hash": source_hash,
        "path": str(path),
        "fileName": source_file,
        "ingestedAt": imported_at,
        "period": {"from": period_from, "to": period_to},
    }

    meta = state.setdefault("meta", {})
    meta["lastImport"] = {
        "sourceFile": source_file,
        "sourcePath": str(path),
        "sourceUid": source_uid,
        "sourceHash": source_hash,
        "importedAt": imported_at,
        "period": {"from": period_from, "to": period_to},
    }

    return {
        "status": "ingested",
        "added": added,
        "dups": dups,
        "skipped": skipped,
        "bad": bad,
        "source_uid": source_uid,
        "source_hash": source_hash,
    }


# ============================================================
# CLI
# ============================================================


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument(
        "json_paths", nargs="*", help="Input JSON files (archived TR_Cash_*.json etc.)"
    )
    p.add_argument(
        "--source-file", default="", help="Original/archived filename for meta"
    )
    p.add_argument(
        "--imported-at",
        default="",
        help="ISO timestamp when pipeline ingested this file",
    )
    p.add_argument("--period-from", default="", help="ISO date YYYY-MM-DD")
    p.add_argument("--period-to", default="", help="ISO date YYYY-MM-DD")
    return p


def main() -> int:
    ap = build_arg_parser()
    args = ap.parse_args()
    log_run_start()
    state = load_state()

    paths: List[Path] = []
    for a in args.json_paths:
        p = Path(a).expanduser()
        if p.exists() and p.is_file():
            paths.append(p)

    if not paths:
        latest = find_latest_json(TR_BASE_DIR)
        if latest:
            paths = [latest]

    if not paths:
        log_run_end("noop")
        return RC_OK

    imported_at = (args.imported_at or "").strip() or now_iso_local()
    period_from = (args.period_from or "").strip()
    period_to = (args.period_to or "").strip()

    total_added = total_dups = total_skipped = total_bad = 0
    last_source_uid = ""
    skipped_sources = 0

    for p in paths:
        source_file = (args.source_file or "").strip() or p.name

        res = ingest_json(
            p,
            state,
            source_file=source_file,
            imported_at=imported_at,
            period_from=period_from,
            period_to=period_to,
        )

        last_source_uid = res.get("source_uid", "") or last_source_uid

        if res.get("status") == "skipped_already_ingested":
            skipped_sources += 1
            continue

        total_added += int(res.get("added", 0))
        total_dups += int(res.get("dups", 0))
        total_skipped += int(res.get("skipped", 0))
        total_bad += int(res.get("bad", 0))

    # ------------------------------------------------------------
    # Entscheiden, ob sich der State wirklich geändert hat
    # geändert = added + dups (dups sind echte neue tx-Keys)
    # ------------------------------------------------------------
    state_changed = (total_added + total_dups) > 0

    # Wenn Quelle schon drin war UND ansonsten gar nix passiert ist -> SKIP
    if skipped_sources and not state_changed:
        _log(
            "J2S",
            f"source already in state -> skipped={skipped_sources} last_source={last_source_uid}",
        )
        log_run_end("skipped")
        return RC_SKIP_ALREADY

    # Wenn keine neuen Einträge hinzugekommen sind -> SKIP (keine updatedAt-Änderung!)
    if not state_changed:
        _log(
            "INFO",
            f"no new tx | skipped={total_skipped} bad={total_bad} last_source={last_source_uid}",
        )
        log_run_end("skipped")
        return RC_SKIP_ALREADY

    # Ab hier: State hat sich geändert -> Stats + Save
    update_stats(state)
    save_state(state)
    _log(
        "J2S",
        f"tr_state updated | added={total_added} dups={total_dups} skipped={total_skipped} bad={total_bad} last_source={last_source_uid}",
    )
    log_run_end("updated")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
