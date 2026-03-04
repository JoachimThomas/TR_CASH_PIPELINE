#!/Library/Frameworks/Python.framework/Versions/3.14/bin/python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from playwright.sync_api import sync_playwright, TimeoutError
from pathlib import Path
import json
import re
import time


# ============================================================
# Return codes (CR-friendly)
#   0  = ok (DESTPATH emitted)
#   10 = no usable input / no json produced (normal end)
#   20 = technical error in P2J (CR may alert)
# ============================================================
RC_OK = 0
RC_NO_INPUT = 10
RC_TECH = 20


def ts() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(level: str, msg: str) -> None:
    # Format aligned with other workers:
    # [YYYY-MM-DD HH:MM:SS] P2J | LEVEL message
    print(f"[{ts()}] P2J | {level} {msg}")


# ============================================================
# CONFIG
# ============================================================

# --- Tool local (file://) ---
TOOL_DIR = "/Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/Trade-Republic-CSV-Excel"
INDEX_HTML = Path(TOOL_DIR) / "index.html"
URL = INDEX_HTML.resolve().as_uri()

# --- Input / Output (INBOX) ---
PDF = "/Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/INBOX_Auzüge/Kontoauszug.pdf"
OUT_DIR = "/Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/INBOX_CASH_JSON"

# --- Archive targets (same conventions as CR) ---
ARCHIVE_JSON_BASE = "/Users/joachimthomas/Finanzverwaltung/Archiv/TradeRepublic/Cash/Kontobewegungen_JSON"
PDF_ARCHIVE_ROOT = (
    "/Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/Auszüge"
)

# --- Timeouts ---
TOOL_READY_TIMEOUT_MS = 10_000
DOWNLOAD_TIMEOUT_MS = 30_000
PDF_STABLE_TIMEOUT_S = 20


# ============================================================
# Helpers (copied/compatible with CR conventions)
# ============================================================


def wait_file_stable(path: Path, timeout_s: int) -> bool:
    """Wait until file exists and size is stable for ~2 seconds."""
    prev = None
    stable = 0
    for _ in range(timeout_s):
        if path.exists() and path.is_file():
            try:
                cur = path.stat().st_size
            except Exception:
                cur = None

            if cur and cur > 0:
                if prev == cur:
                    stable += 1
                else:
                    stable = 0
                prev = cur
                if stable >= 2:
                    return True
        time.sleep(1)
    return False


def unique_dest(dest: Path) -> Path:
    if not dest.exists():
        return dest
    base = dest.with_suffix("")
    ext = dest.suffix
    i = 2
    while True:
        cand = Path(f"{base}_{i}{ext}")
        if not cand.exists():
            return cand
        i += 1


_MONTH_MAP = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "mär": "03",
    "mae": "03",
    "mrz": "03",
    "apr": "04",
    "mai": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "sept": "09",
    "okt": "10",
    "nov": "11",
    "dez": "12",
}

_DATE_RE = re.compile(r"^\s*(\d{1,2})\s+([A-Za-zÄÖÜäöü]{3,5})\.?\s+(\d{4})(?:\b.*)?$")


def _to_iso_date(s: str) -> str | None:
    if not s:
        return None
    m = _DATE_RE.match(str(s))
    if not m:
        return None
    dd = int(m.group(1))
    mm_raw = m.group(2).strip().lower()
    yyyy = int(m.group(3))
    mm = _MONTH_MAP.get(mm_raw) or _MONTH_MAP.get(mm_raw[:3])
    if not mm:
        return None
    return f"{yyyy:04d}-{mm}-{dd:02d}"


def extract_min_max_dates(json_path: Path) -> tuple[str, str, int]:
    """Return (min_date, max_date, count_candidates) as YYYY-MM-DD."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return "", "", 0

    dates: set[str] = set()

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                k_l = str(k).strip().lower()
                if isinstance(v, str):
                    if k_l in (
                        "datum",
                        "date",
                        "bookingdate",
                        "valutadate",
                    ) or k_l.endswith("date"):
                        iso = _to_iso_date(v)
                        if iso:
                            dates.add(iso)
                    iso2 = _to_iso_date(v)
                    if iso2:
                        dates.add(iso2)
                walk(v)
        elif isinstance(obj, list):
            for it in obj:
                walk(it)
        else:
            if isinstance(obj, str):
                iso = _to_iso_date(obj)
                if iso:
                    dates.add(iso)

    walk(data)

    sdates = sorted(dates)
    if not sdates:
        return "", "", 0
    return sdates[0], sdates[-1], len(sdates)


def build_year_month(max_date: str) -> tuple[str, str]:
    # expects YYYY-MM-DD
    if re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", max_date or ""):
        return max_date[0:4], max_date[5:7]
    return "unknown", "00"


# ============================================================
# Main
# ============================================================


def main() -> int:
    out_dir = Path(OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_in = Path(PDF)
    if not wait_file_stable(pdf_in, PDF_STABLE_TIMEOUT_S):
        log("WARN", f"pdf_not_ready | path={pdf_in}")
        log("END", "result=no_input")
        return RC_NO_INPUT

    # --- Playwright: load tool via file:// and export JSON ---
    tmp_dl: Path | None = None
    json_inbox = out_dir / "cash.json"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(accept_downloads=True)
            page = ctx.new_page()

            page.goto(URL)

            try:
                page.wait_for_selector(
                    "input[type=file]", timeout=TOOL_READY_TIMEOUT_MS
                )
            except Exception as e:
                log("WARN", f"tool_not_ready | url={URL} | err={e}")
                log("END", "result=tool_not_ready")
                return RC_TECH

            try:
                page.set_input_files("input[type=file]", str(pdf_in))
                log("INFO", f"pdf_selected | path={pdf_in}")
            except Exception as e:
                log("WARN", f"file_input_missing | selector=input[type=file] | err={e}")
                log("END", "result=file_input_missing")
                return RC_TECH

            # Expect JSON download
            try:
                with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as dlinfo:
                    page.get_by_role("button", name="JSON").click()

                dl = dlinfo.value
                # Write to a tmp file first, then atomically replace cash.json
                tmp_dl = out_dir / (dl.suggested_filename or "export.json")
                dl.save_as(str(tmp_dl))

            except TimeoutError:
                log("WARN", f"no_json_download | timeout_ms={DOWNLOAD_TIMEOUT_MS}")
                log("END", "result=no_json")
                return RC_NO_INPUT

        finally:
            # ALWAYS close the browser
            try:
                browser.close()
            except Exception:
                pass

    if tmp_dl is None or not tmp_dl.exists():
        log("WARN", "download_missing_after_save")
        log("END", "result=no_json")
        return RC_NO_INPUT

    # Normalize: always use INBOX name cash.json (so CR/launchd expectations stay sane)
    try:
        # Ensure non-empty
        if not wait_file_stable(tmp_dl, 10):
            log("WARN", f"json_not_stable | path={tmp_dl}")
            log("END", "result=no_json")
            return RC_NO_INPUT

        # Validate JSON parse
        try:
            _ = json.loads(tmp_dl.read_text(encoding="utf-8"))
        except Exception as e:
            log("WARN", f"json_invalid | path={tmp_dl} | err={e}")
            log("END", "result=no_json")
            return RC_NO_INPUT

        # Atomic replace to cash.json
        tmp_target = json_inbox.with_suffix(json_inbox.suffix + ".tmp")
        tmp_target.write_text(tmp_dl.read_text(encoding="utf-8"), encoding="utf-8")
        tmp_target.replace(json_inbox)

        # Cleanup the original suggested file if different
        if tmp_dl.resolve() != json_inbox.resolve():
            try:
                tmp_dl.unlink(missing_ok=True)
            except Exception:
                pass

        log("INFO", f"json_saved | path={json_inbox}")

    finally:
        # Best-effort cleanup
        try:
            if tmp_dl and tmp_dl.exists() and tmp_dl.name != "cash.json":
                tmp_dl.unlink(missing_ok=True)
        except Exception:
            pass

    # --- Determine MIN/MAX + archive destinations ---
    min_date, max_date, date_count = extract_min_max_dates(json_inbox)
    if date_count == 0 or not min_date or not max_date:
        log("WARN", f"json_not_usable_no_date_coverage | path={json_inbox}")
        log("END", "result=no_coverage")
        return RC_NO_INPUT

    year, month = build_year_month(max_date)

    # Archive JSON
    dest_dir_json = Path(ARCHIVE_JSON_BASE) / year / month
    dest_dir_json.mkdir(parents=True, exist_ok=True)

    new_json_name = f"TR_Cash_{min_date}_bis_{max_date}.json"
    dest_json = unique_dest(dest_dir_json / new_json_name)

    try:
        json_inbox.replace(dest_json)
        log("INFO", f"json_archived | dest={dest_json}")
    except Exception as e:
        log("WARN", f"json_archive_failed | dest={dest_json} | err={e}")
        log("END", "result=archive_failed")
        return RC_TECH

    # Archive PDF
    dest_dir_pdf = Path(PDF_ARCHIVE_ROOT) / year / month
    dest_dir_pdf.mkdir(parents=True, exist_ok=True)

    pdf_name = f"TR_Cash_{min_date}_bis_{max_date}.pdf"
    dest_pdf = unique_dest(dest_dir_pdf / pdf_name)

    if wait_file_stable(pdf_in, 10):
        try:
            pdf_in.replace(dest_pdf)
            log("INFO", f"pdf_saved | dest={dest_pdf}")
        except Exception as e:
            log("WARN", f"pdf_move_failed | dest={dest_pdf} | err={e}")
    else:
        log("WARN", f"pdf_not_found_or_not_stable | path={pdf_in}")

    # Final: provide CR the archived JSON path (DESTPATH)
    log("END", f"result=ok | dest={dest_json} | min={min_date} | max={max_date}")
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
