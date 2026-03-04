#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import json
import time
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
import pdfplumber
import subprocess

# ------------------------------------------------------------
# Notify (Global)
#   Uses: /Users/joachimthomas/Finanzverwaltung/Programme/Global/finance_notify.sh
#   Only ONE notification per run: OK or FAIL.
# ------------------------------------------------------------
NOTIFY_SH = "/Users/joachimthomas/Finanzverwaltung/Programme/Global/finance_notify.sh"
NOTIFY_ISSUER = "TR_CASH"  # Issuer is TR-Cash
NOTIFY_CALLER = "TR_Zinsen_Parser"


def notify(level: str, message: str):
    """level: OK | INFO | WARN | FAIL"""
    try:
        subprocess.run(
            [NOTIFY_SH, NOTIFY_ISSUER, level, message, NOTIFY_CALLER],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        # Never crash because notifications fail
        pass


# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

# Eingang: hier landen die TR-Zins-/Dividenden-Abrechnungs-PDFs
IN_DIR = Path("/Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/INBOX_ZINS")

# Archiv (lesbar, dauerhaft)
ARCH_PDF = Path("/Users/joachimthomas/Finanzverwaltung/Archiv/TradeRepublic/Cash/Zinsabrechnungen")

# Global State (App Support)
STATE_DIR = Path.home() / "Library" / "Application Support" / "Finanzen"
GLOBAL_STATE_PATH = STATE_DIR / "global_capital_revenues_taxes.json"

MONEY_RE = r"[+\-]?\s*[\d\.]+,\d{2}"


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def ensure_dirs():
    IN_DIR.mkdir(parents=True, exist_ok=True)
    ARCH_PDF.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def stable_wait(p: Path, loops=60, sleep_s=0.2):
    last = -1
    stable = 0
    for _ in range(loops):
        try:
            sz = p.stat().st_size
        except Exception:
            time.sleep(sleep_s)
            continue
        if sz == last and sz > 0:
            stable += 1
            if stable >= 4:
                return
        else:
            stable = 0
            last = sz
        time.sleep(sleep_s)


def unique_dest(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suf = dest.stem, dest.suffix
    i = 2
    while True:
        cand = dest.with_name(f"{stem}_{i}{suf}")
        if not cand.exists():
            return cand
        i += 1


def de_money_to_float(s: str) -> float:
    s = (s or "").strip().replace("EUR", "").replace("€", "").strip()
    if not s:
        return 0.0
    s = s.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def pick(pattern, text, flags=0, default=""):
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else default


def parse_ddmmyyyy(s: str):
    try:
        return datetime.strptime(s, "%d.%m.%Y")
    except Exception:
        return None


def ddmmyyyy_to_ymd(s: str) -> str:
    dt = parse_ddmmyyyy(s or "")
    return dt.strftime("%Y-%m-%d") if dt else ""


def safe_filename(s: str) -> str:
    s = (s or "").strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9._-]+", "", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("._-") or "unknown"


def sha1_16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def extract_text(pdf_path: Path) -> str:
    with pdfplumber.open(str(pdf_path)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


# ------------------------------------------------------------
# Parsing: TR "ABRECHNUNG - ZINSEN" / "ABRECHNUNG - DIVIDENDE"
# ------------------------------------------------------------
# This parser considers 4 blocks:
#  1) ÜBERSICHT (gross per asset line)
#  2) ABRECHNUNG - ZINSEN (Cash: gross/kest/soli/net)
#  3) ABRECHNUNG - DIVIDENDE (Geldmarkt: gross/kest/soli/net)
#  4) BUCHUNG (net credited after taxes) -> stored as synthetic entry incomeType="Buchung"
def parse_block_values(text: str, block_name: str) -> dict:
    """
    block_name: "ZINSEN" oder "DIVIDENDE"
    liest aus:
      ABRECHNUNG - <block_name>
      Besteuerungsgrundlage X
      Kapitalertragsteuer Y
      Solidaritätszuschlag Z
      Gesamt N
    """
    out = {"gross": 0.0, "kest": 0.0, "soli": 0.0, "net": 0.0}
    m = re.search(
        rf"\bABRECHNUNG\s*-\s*{re.escape(block_name)}\b(.*?)(\bABRECHNUNG\b|\bBUCHUNG\b|$)",
        text,
        flags=re.S | re.I,
    )
    if not m:
        return out
    blk = m.group(1)

    def money_after(label: str) -> float:
        mm = re.search(rf"{re.escape(label)}\s+({MONEY_RE})\s+EUR", blk, flags=re.I)
        return de_money_to_float(mm.group(1)) if mm else 0.0

    out["gross"] = money_after("Besteuerungsgrundlage")
    out["kest"] = money_after("Kapitalertragsteuer")
    out["soli"] = money_after("Solidaritätszuschlag")
    out["net"] = money_after("Gesamt")
    return out


# --- Helper to parse BUCHUNG (net after taxes) ---
def parse_booking_net(text: str) -> float:
    """Parse BUCHUNG block: ... GUTSCHRIFT NACH STEUERN <amount> EUR"""
    m = re.search(
        rf"\bBUCHUNG\b.*?\bGUTSCHRIFT\s+NACH\s+STEUERN\b\s+({MONEY_RE})\s+EUR\b",
        text,
        flags=re.S | re.I,
    )
    return de_money_to_float(m.group(1)) if m else 0.0


def parse_overview_lines(text: str) -> list:
    """
    ÜBERSICHT-Tabelle (Beispiele):
    Cash Zinsen 2,00% 01.11.2025 - 30.11.2025 21,48 EUR
    Geldmarkt Dividende 2,00% 01.11.2025 - 30.11.2025 140,24 EUR
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if (ln or "").strip()]
    out = []
    for ln in lines:
        if not re.search(r"\bEUR\b", ln, flags=re.I):
            continue
        if not re.search(r"\b(Zinsen|Dividende)\b", ln, flags=re.I):
            continue

        pm = re.search(r"(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})", ln)
        if not pm:
            continue
        p_from, p_to = pm.group(1), pm.group(2)

        mm = re.search(rf"({MONEY_RE})\s+EUR\b", ln)
        if not mm:
            continue
        gross = de_money_to_float(mm.group(1))

        it = (
            "Zinsen"
            if re.search(r"\bZinsen\b", ln, flags=re.I)
            else ("Dividende" if re.search(r"\bDividende\b", ln, flags=re.I) else "")
        )
        if not it:
            continue

        am = re.search(rf"^\s*(.+?)\s+{it}\b", ln, flags=re.I)
        asset = (am.group(1).strip() if am else "").strip()
        if not asset:
            continue

        out.append(
            {
                "asset": asset,
                "incomeType": it,
                "periodFrom": p_from,
                "periodTo": p_to,
                "gross": gross,
            }
        )
    return out


def parse_one_pdf(text: str, source_pdf: str) -> dict:
    doc_date = pick(r"\bDATUM\s+(\d{2}\.\d{2}\.\d{4})\b", text, flags=re.I)
    as_of = pick(r"\bzum\s+(\d{2}\.\d{2}\.\d{4})\b", text, flags=re.I)

    booking_date = pick(
        r"\bIBAN\s+BUCHUNGSDATUM\b.*?\b(\d{2}\.\d{2}\.\d{4})\b", text, flags=re.S | re.I
    )
    if not booking_date:
        booking_date = doc_date

    z_block = parse_block_values(text, "ZINSEN")
    d_block = parse_block_values(text, "DIVIDENDE")
    booking_net = parse_booking_net(text)

    overview = parse_overview_lines(text)
    block_by_type = {"Zinsen": z_block, "Dividende": d_block}

    entries = []
    for ov in overview:
        it = ov.get("incomeType", "")
        blk = block_by_type.get(it, {"gross": 0.0, "kest": 0.0, "soli": 0.0, "net": 0.0})

        gross = blk.get("gross", 0.0) if abs(blk.get("gross", 0.0)) > 1e-9 else ov.get("gross", 0.0)
        kest = blk.get("kest", 0.0)
        soli = blk.get("soli", 0.0)
        net = blk.get("net", 0.0)

        entry = {
            "source_pdf": source_pdf,
            "docDate": ddmmyyyy_to_ymd(doc_date),
            "asOfDate": ddmmyyyy_to_ymd(as_of),
            "bookingDate": ddmmyyyy_to_ymd(booking_date),
            "periodFrom": ddmmyyyy_to_ymd(ov.get("periodFrom", "")),
            "periodTo": ddmmyyyy_to_ymd(ov.get("periodTo", "")),
            "asset": ov.get("asset", ""),
            "incomeType": it,
            "gross": float(gross or 0.0),
            "kest": float(kest or 0.0),
            "soli": float(soli or 0.0),
            "net": float(net or 0.0),
        }

        uid_base = "|".join(
            [
                entry.get("bookingDate", ""),
                entry.get("asOfDate", ""),
                entry.get("periodFrom", ""),
                entry.get("periodTo", ""),
                entry.get("asset", ""),
                entry.get("incomeType", ""),
                f"{entry.get('gross',0.0):.2f}",
                f"{entry.get('kest',0.0):.2f}",
                f"{entry.get('soli',0.0):.2f}",
                f"{entry.get('net',0.0):.2f}",
            ]
        )
        entry["source_uid"] = sha1_16(uid_base)

        if entry["incomeType"] and abs(entry["gross"]) > 1e-9:
            entries.append(entry)

    # --- Totals across both blocks (Cash + Geldmarkt) ---
    gross_total = float(sum((it.get("gross") or 0.0) for it in entries))
    kest_total = float(sum((it.get("kest") or 0.0) for it in entries))
    soli_total = float(sum((it.get("soli") or 0.0) for it in entries))

    # Synthetic summary entry for the BUCHUNG (net credited after taxes)
    # This allows easy reconciliation: gross_total ≈ booking_net + (-kest_total) + (-soli_total)
    if abs(booking_net) > 1e-9 and abs(gross_total) > 1e-9:
        booking_entry = {
            "source_pdf": source_pdf,
            "docDate": ddmmyyyy_to_ymd(doc_date),
            "asOfDate": ddmmyyyy_to_ymd(as_of),
            "bookingDate": ddmmyyyy_to_ymd(booking_date),
            "periodFrom": ddmmyyyy_to_ymd(
                min((it.get("periodFrom") or "") for it in entries) or ""
            ),
            "periodTo": ddmmyyyy_to_ymd(max((it.get("periodTo") or "") for it in entries) or ""),
            "asset": "TR Gesamt",
            "incomeType": "Buchung",
            "gross": float(gross_total),
            "kest": float(kest_total),
            "soli": float(soli_total),
            "net": float(booking_net),
        }

        uid_base = "|".join(
            [
                booking_entry.get("bookingDate", ""),
                booking_entry.get("asOfDate", ""),
                booking_entry.get("periodFrom", ""),
                booking_entry.get("periodTo", ""),
                booking_entry.get("asset", ""),
                booking_entry.get("incomeType", ""),
                f"{booking_entry.get('gross', 0.0):.2f}",
                f"{booking_entry.get('kest', 0.0):.2f}",
                f"{booking_entry.get('soli', 0.0):.2f}",
                f"{booking_entry.get('net', 0.0):.2f}",
            ]
        )
        booking_entry["source_uid"] = sha1_16(uid_base)
        entries.append(booking_entry)

    return {
        "docDate": ddmmyyyy_to_ymd(doc_date),
        "asOfDate": ddmmyyyy_to_ymd(as_of),
        "bookingDate": ddmmyyyy_to_ymd(booking_date),
        "bookingNet": float(booking_net or 0.0),
        "entries": entries,
    }


def build_archive_pdf_name(meta: dict, fallback_name: str) -> str:
    asof = safe_filename(meta.get("asOfDate", "") or "")
    book = safe_filename(meta.get("bookingDate", "") or "")
    if asof and book and asof != "unknown" and book != "unknown":
        return f"TR_Zinsen_{asof}_book_{book}.pdf"
    return safe_filename(Path(fallback_name).name)


# ------------------------------------------------------------
# Global State I/O
# ------------------------------------------------------------
def load_global_state() -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    if not GLOBAL_STATE_PATH.exists():
        return {
            "meta": {"schema": "global_capital_revenues_taxes_v1", "created": now, "updated": now},
            "entries": {},
            "stats": {},
        }
    try:
        d = json.loads(GLOBAL_STATE_PATH.read_text(encoding="utf-8"))
        if "entries" not in d or not isinstance(d["entries"], dict):
            d["entries"] = {}
        if "meta" not in d or not isinstance(d["meta"], dict):
            d["meta"] = {}
        if "stats" not in d or not isinstance(d["stats"], dict):
            d["stats"] = {}
        if not d["meta"].get("schema"):
            d["meta"]["schema"] = "global_capital_revenues_taxes_v1"
        return d
    except Exception:
        return {
            "meta": {"schema": "global_capital_revenues_taxes_v1", "created": now, "updated": now},
            "entries": {},
            "stats": {},
        }


def atomic_write_json(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def compute_stats(entries: dict) -> dict:
    """Compute simple aggregates for quick sanity checks."""
    tx_count = 0
    sum_kev = 0.0
    sum_kest = 0.0
    sum_soli = 0.0
    sum_kenet = 0.0

    if not isinstance(entries, dict):
        entries = {}

    for _uid, e in entries.items():
        if not isinstance(e, dict):
            continue
        tx_count += 1

        def f(key: str) -> float:
            v = e.get(key, 0.0)
            try:
                return float(v)
            except Exception:
                return 0.0

        sum_kev += f("kevSteu")
        sum_kest += f("kest")
        sum_soli += f("soli")
        sum_kenet += f("keNet")

    return {
        "txCount": int(tx_count),
        "sumKevSteu": round(sum_kev, 2),
        "sumKest": round(sum_kest, 2),
        "sumSoli": round(sum_soli, 2),
        "sumKeNet": round(sum_kenet, 2),
    }


def asset_type_from(asset: str) -> str:
    a = (asset or "").strip().lower()
    if a == "cash":
        return "Cash"
    if "geldmarkt" in a:
        return "Geldmarkt"
    return "Cash"


def make_global_entry(e: dict, archived_pdf_name: str) -> dict:
    issuer = "Trade Republic"
    source_system = "TradeRepublic"
    account = "TR_Verrechnungskonto"

    doc_date = (e.get("docDate") or "").strip()
    asof_date = (e.get("asOfDate") or "").strip()
    book_date = (e.get("bookingDate") or "").strip()
    p_from = (e.get("periodFrom") or "").strip()
    p_to = (e.get("periodTo") or "").strip()

    asset = (e.get("asset") or "").strip()
    income_type = (e.get("incomeType") or "").strip()

    gross = float(e.get("gross") or 0.0)
    kest = float(e.get("kest") or 0.0)
    soli = float(e.get("soli") or 0.0)
    net = float(e.get("net") or 0.0)

    # steuerwirksamer Kapitalertrag:
    # - For Zinsen/Dividende entries: gross is the taxable base ("Besteuerungsgrundlage").
    # - For the synthetic Buchung entry: gross is the total taxable amount across blocks.
    kev_steu = gross
    ke_net = net

    source_uid = (e.get("source_uid") or "").strip()

    # Global UID stabil
    uid_base = "|".join(
        [
            "TR",
            archived_pdf_name,
            doc_date,
            asof_date,
            book_date,
            p_from,
            p_to,
            asset,
            income_type,
            f"{gross:.2f}",
            f"{kest:.2f}",
            f"{soli:.2f}",
            f"{net:.2f}",
            source_uid,
        ]
    )
    uid = sha1_16(uid_base)

    return {
        "uid": uid,
        "issuer": issuer,
        "sourceSystem": source_system,
        "account": account,
        "sourceRef": archived_pdf_name,
        "sourceKind": "pdf",
        "sourceUid": source_uid,
        "docDate": doc_date,
        "asOfDate": asof_date,
        "bookingDate": book_date,
        "periodFrom": p_from,
        "periodTo": p_to,
        "assetType": asset_type_from(asset),
        "asset": asset,
        "assetName": "",
        "incomeType": income_type,  # "Zinsen" / "Dividende"
        "currency": "EUR",
        "kevSteu": round(kev_steu, 2),
        "kest": round(kest, 2),
        "soli": round(soli, 2),
        "keNet": round(ke_net, 2),
        "note": f"TR-{income_type} asset={asset} period={p_from}..{p_to} gross={gross:.2f} kest={kest:.2f} soli={soli:.2f} net={net:.2f}",
    }


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    ensure_dirs()

    pdfs = sorted(IN_DIR.glob("*.pdf"))
    if not pdfs:
        return 10, "Keine neuen TR-Zins-/Dividendenabrechnungen."

    st = load_global_state()
    ent = st.get("entries", {}) or {}
    known = set(ent.keys())

    added_total = 0
    processed = 0
    failed = 0

    for p in pdfs:
        stable_wait(p)
        processed += 1

        parsed_meta = {}
        try:
            text = extract_text(p)
            parsed_meta = parse_one_pdf(text, p.name)
        except Exception:
            parsed_meta = {}

        arch_name = build_archive_pdf_name(parsed_meta or {}, p.name)
        dest = unique_dest(ARCH_PDF / arch_name)

        try:
            shutil.move(str(p), str(dest))
        except Exception:
            failed += 1
            continue

        for e in parsed_meta.get("entries") or []:
            ge = make_global_entry(e, dest.name)
            uid = (ge.get("uid") or "").strip()
            if not uid:
                continue
            if uid in known:
                continue

            ent[uid] = ge
            known.add(uid)
            added_total += 1

    st["entries"] = ent

    # stats (quick aggregates)
    st["stats"] = compute_stats(ent)

    # Update metadata
    st.setdefault("meta", {})
    st["meta"]["updated"] = datetime.now().isoformat(timespec="seconds")
    atomic_write_json(GLOBAL_STATE_PATH, st)

    # Build result message for caller
    if failed > 0:
        return (
            20,
            f"Teilweise verarbeitet: PDFs={processed}, Fehler={failed}, neue Einträge={added_total}.",
        )
    return 0, f"Verarbeitet: PDFs={processed}, neue Einträge={added_total}."


if __name__ == "__main__":
    try:
        rc, msg = main()
        if rc == 0:
            notify("OK", msg)
        elif rc == 10:
            notify("OK", msg)
        else:
            notify("FAIL", msg)
    except Exception as e:
        notify("FAIL", f"Abbruch: {type(e).__name__}: {e}")
