TTDAR — Log- & Notification-System (TR-Cash) 📒🔔
Stand: 15.02.2026

============================================================
1) Ziel & Prinzip
============================================================
Dieses Projekt bildet eine robuste, „KISS aber professionell“-Pipeline für TradeRepublic Cash-Auszüge:

- Trigger: Eingang eines PDF-Auszugs in einer INBOX
- Toolserver + Min werden von der Pipeline intern gestartet/gestoppt
- JSON wird in separater INBOX erwartet (fixer Name cash.json)
- JSON wird archiviert (YYYY/MM) und umbenannt (TR_Cash_MIN_bis_MAX.json)
- PDF wird umbenannt und einsortiert (YYYY/MM) (TR_Cash_MIN_bis_MAX.pdf)
- Worker-Aufrufe:
  - J2S: JSON -> State (tr_state.json)
  - S2R: State -> Reports (+ optional global update)
- Notifikationen kommen NUR aus CRP (zentral), Reihenfolge ist deterministisch
- Logging ist kurz, stabil, kopierbar, mit LogCut (letzter Run bleibt)

============================================================
2) Komponenten (4 Scripts) & Rollen
============================================================

(1) CRP — tr_cash_run.sh
Pfad:
  /Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/tr_cash_run.sh

Rolle:
  Zentrale Pipeline (Toolserver + Min intern) + Logging + Notis
  Ruft J2S und S2R auf und wertet RCs aus.

(2) J2S — tr_state_from_json.py
Pfad:
  /Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/tr_state_from_json.py

Rolle:
  Ingest von JSON in State:
  - dedupe über Source Hash
  - RC=0: State geändert
  - RC=10: bereits erfasst / keine neuen tx-Keys

Logging minimal, Tag [J2S].

(3) S2R — tr_reports_from_tr_state.py
Pfad:
  /Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/tr_reports_from_tr_state.py

Rolle:
  Reports aus State erzeugen.
  Schreibt Logzeilen, die CRP auswertet (z.B. Monat + Rows).
  (Notis aus S2R werden NICHT genutzt — nur Logs, Notis zentral in CRP)

(4) Trigger-Wrapper — run_tr_cash_run_from_inbox_pdf.sh
Pfad:
  /Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/run_tr_cash_run_from_inbox_pdf.sh

Rolle:
  Minimaler Start-Hook (z.B. launchd): prüft, ob Kontoauszug.pdf in INBOX liegt und startet CRP.

============================================================
3) Ordnerstruktur (INBOX / Archive / State / Reports)
============================================================

INBOX PDF (Trigger):
  /Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/INBOX_Auzüge
  Datei: Kontoauszug.pdf

INBOX JSON:
  /Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/INBOX_CASH_JSON
  Datei: cash.json

Archiv JSON:
  /Users/joachimthomas/Finanzverwaltung/Archiv/TradeRepublic/Cash/Kontobewegungen_JSON/YYYY/MM/
  Name: TR_Cash_<MIN_DATE>_bis_<MAX_DATE>[_n].json

Archiv PDF (Ablage):
  /Users/joachimthomas/Documents/Joachim privat/Banken/Trade Republic/Auszüge/YYYY/MM/
  Name: TR_Cash_<MIN_DATE>_bis_<MAX_DATE>[_n].pdf

State:
  ~/Library/Application Support/Finanzen/TR_CASH/tr_state.json

CRP Logfile:
  /Users/joachimthomas/Finanzverwaltung/Programme/Logs/TradeRepublic-Cash/tr_cash_run.log

============================================================
4) Ablauf (Flowchart) 🧭
============================================================

Trigger (launchd / wrapper):
  ┌─────────────────────────────────────────────────────┐
  │ (4) run_tr_cash_run_from_inbox_pdf.sh                │
  │  - wenn INBOX_Auzüge/Kontoauszug.pdf existiert:     │
  │    -> CRP starten                                   │
  └─────────────────────────────────────────────────────┘
                        │
                        v
  ┌─────────────────────────────────────────────────────┐
  │ (1) CRP tr_cash_run.sh                               │
  │  A) START: Log + Noti "TR-Cash-Run gestartet"        │
  │  B) Toolserver starten (python -m http.server)       │
  │  C) Min öffnen (URL localhost:8000)                  │
  │  D) Warte bis INBOX_CASH_JSON/cash.json stable (300s)│
  └─────────────────────────────────────────────────────┘
        │                         │
        │ JSON kommt               │ Timeout (kein JSON)
        v                         v
  ┌──────────────────────────┐   ┌─────────────────────────────────────────┐
  │ E) Parse MIN/MAX aus JSON │   │ Timeout-Branch                          │
  │ F) JSON archivieren       │   │  - Min quit + Server stop               │
  │ G) Server+Min schließen   │   │  - Noti: "Server und MIN-Browser beendet"│
  │ H) PDF stable check (20s) │   │  - Noti WARN: "Ende ... keine JSON 300s"│
  │ I) PDF umbenennen+move    │   │  - END no_input_timeout                 │
  └──────────────────────────┘   └─────────────────────────────────────────┘
        │
        v
  ┌─────────────────────────────────────────────────────┐
  │ J) Worker J2S (JSON -> State)                        │
  │  - RC=10: "State war bereits aktuell" -> END         │
  │  - RC!=0: FAIL -> END                                │
  │  - RC=0 : parse "added=X" -> Noti "State aktualisiert (+X)"│
  └─────────────────────────────────────────────────────┘
        │
        v
  ┌─────────────────────────────────────────────────────┐
  │ K) Worker S2R (State -> Reports)                     │
  │  - parse log: "[S2R] report_updated | month=YYYY-MM rows=N"│
  │    -> Noti: "Report MM.YYYY mit N Einträgen aktualisiert." │
  │  - optional parse global updated -> Noti "Global updated: VALUE"│
  └─────────────────────────────────────────────────────┘
        │
        v
  ┌─────────────────────────────────────────────────────┐
  │ L) END: Noti "TR-Cash-Run beendet" + Log END         │
  └─────────────────────────────────────────────────────┘

============================================================
5) Logging: Format, LogCut, wichtige Zeilen 🧾
============================================================

Logformat (CRP):
  [YYYY-MM-DD HH:MM:SS] CRP | <MESSAGE>

Anchor (für LogCut):
  "CRP | START TR-CASH-RUN | run_id="
LogCut-Regel:
  - Beim Start wird das Log so gekürzt, dass nur der letzte Run plus der neue Run erhalten bleiben.
  - Technik: letzte Anchor-Zeile suchen -> ab dort tailen -> Log überschreiben.

Kern-Logereignisse (CRP):
  START:
    CRP | START TR-CASH-RUN | run_id=TRCASH_YYYYMMDD_HHMMSS
  JSON gefunden:
    CRP | INFO input_json=/.../INBOX_CASH_JSON/cash.json
  JSON archiviert:
    CRP | INFO archive_move_to=/.../Kontobewegungen_JSON/YYYY/MM/TR_Cash_...json
  Warns:
    CRP | WARN pdf_not_found_or_not_stable | inbox=...
  Ende:
    CRP | END TR-CASH-RUN | result=<...> | rc=0 | run_id=...

J2S minimal logs:
  [YYYY-MM-DD HH:MM:SS] [J2S] start tr_state_from_json
  [YYYY-MM-DD HH:MM:SS] [J2S] tr_state updated | added=... dups=... ...
  [YYYY-MM-DD HH:MM:SS] [J2S] source already in state -> skipped=... last_source=...
  [YYYY-MM-DD HH:MM:SS] [J2S] end | result=updated|skipped|noop

S2R log line, die CRP auswertet (wichtig!):
  [S2R] report_updated | month=YYYY-MM rows=N

============================================================
6) Notifications: zentral, Reihenfolge, Texte 🔔
============================================================

Caller:
  "TR-Cash-Run-Pipeline" (CALLER in CRP)
Notify-Funktion:
  finance_notify.sh wird immer mit:
    (AccountKey="TR_CASH", Level, Message, Caller)

Noti-Reihenfolge (Normalfall):
  1) OK   "TR-Cash-Run gestartet"
  2) INFO "PDF: Kontobewegungen vom MIN bis MAX gelesen."
  3) INFO "State aktualisiert (+X)"    (nur bei J2S RC=0)
     ODER
     INFO "State war bereits aktuell"  (bei J2S RC=10)
  4) INFO "Report MM.YYYY mit N Einträgen aktualisiert." (wenn S2R Log vorhanden)
  5) INFO "Global updated: VALUE"      (optional, wenn S2R Log vorhanden)
  6) OK   "TR-Cash-Run beendet"

Timeout-Fall (kein JSON in 300s):
  - INFO "Server und MIN-Browser beendet"
  - WARN "Ende TR-Cash-Run: keine JSON in 300s"
  - Log END no_input_timeout
  (Exit bleibt 0; launchd soll nicht meckern.)

Failure-Fall (unerwartet):
  - FAIL "TR-Cash-Run: unerwarteter Fehler (rc=...)" (nur 1x, FAIL_SENT guard)
  - Exit 0 (launchd schweigt trotzdem)
  - Zusätzlich werden bekannte Worker-RCs NICHT als unexpected gefeuert (IN_WORKER=1 guard)

============================================================
7) Returncodes & Fehlerlogik (KISS, aber sauber) 🧨
============================================================

CRP endet IMMER mit rc=0 nach außen.
Dafür gibt es interne Bewertung + Noti:

- python3 fehlt:
  FAIL "Ende TR-Cash-Run: python3 nicht gefunden"
  result=fail_no_python

J2S (tr_state_from_json.py):
- RC=0  -> OK/Update (State geändert)
- RC=10 -> Skip (bereits ingested / keine neuen tx-Keys)
- RC!=0 -> FAIL (Fehler JSON->State)

S2R:
- RC=0  -> OK
- RC!=0 -> WARN "Reports: Fehler (RC=...)"

Unerwartete Fehler (zsh TRAPZERR):
- nur wenn NICHT in Worker-Phase (IN_WORKER=0)
- nur wenn noch kein FAIL gesendet wurde (FAIL_SENT=0)
- sendet FAIL-Alert, loggt "CRP | FAIL unexpected ...", exit 0

============================================================
8) J2S Stats: „currentBalance“ & „lastPeriod“ ✅
============================================================

J2S berechnet in update_stats():

- txCount, minBookingDate, maxBookingDate aus tx
- currentBalance + currentBalanceAsOfDate:
  -> aus dem tx dessen Bookingdate am nächsten zu heute liegt (bevorzugt <= heute)
- lastPeriodFrom / lastPeriodTo:
  -> aus der zuletzt ingested Source (höchstes ingestedAt), period.from/to

Fallback-Suchpfad (Legacy):
- Wenn kein JSON als Arg übergeben wird, sucht J2S im TR_BASE_DIR
- TR_BASE_DIR zeigt standardmäßig auf INBOX_CASH_JSON (nicht Downloads),
  optional über env TR_CASH_INBOX_JSON überschreibbar.

============================================================
9) Betrieb: „Wie benutze ich das?“ 🟢
============================================================

Normaler Ablauf:
1) PDF in INBOX_Auzüge als "Kontoauszug.pdf" ablegen (oder landet dort automatisiert)
2) trigger startet run_tr_cash_run_from_inbox_pdf.sh
3) wrapper startet CRP
4) CRP erledigt alles

Manueller Test:
  zsh /Users/joachimthomas/Finanzverwaltung/Programme/Traderepublic/TradeRepublic-Cash/tr_cash_run.sh

============================================================
10) Typische Log-/Noti-Beispiele 📌
============================================================

Beispiel-Log (kurz):
  [2026-02-15 14:51:26] CRP | START TR-CASH-RUN | run_id=TRCASH_...
  [2026-02-15 14:51:27] CRP | INFO input_json=/.../INBOX_CASH_JSON/cash.json
  [2026-02-15 14:51:27] CRP | INFO archive_move_to=/.../Kontobewegungen_JSON/2026/02/TR_Cash_...json
  [2026-02-15 14:51:27] [J2S] tr_state updated | added=14 ...
  [2026-02-15 14:51:27] [S2R] report_updated | month=2026-02 rows=47
  [2026-02-15 14:51:27] CRP | END TR-CASH-RUN | result=ok | rc=0 | run_id=...

Beispiel-Notis:
  OK   TR-Cash-Run gestartet
  INFO PDF: Kontobewegungen vom 2026-02-01 bis 2026-02-13 gelesen.
  INFO State aktualisiert (+14)
  INFO Report 02.2026 mit 47 Einträgen aktualisiert.
  INFO Global updated: 83514.32
  OK   TR-Cash-Run beendet

============================================================
11) Copy-Paste Checkliste für neue Konten (Blueprint) 🧩
============================================================

- [ ] Definiere INBOX_PDF + Dateiname (fix!)
- [ ] Definiere INBOX_JSON + Dateiname (fix!)
- [ ] Pipeline (CRP) zentralisiert:
      - Logging + LogCut
      - Notis nur aus CRP (Caller stabil)
      - Worker-RCs sauber klassifizieren
      - Unexpected-Guard via TRAPZERR + IN_WORKER
- [ ] Archivstruktur:
      - JSON: YYYY/MM + unique_dest
      - PDF: YYYY/MM + unique_dest
- [ ] Worker 1: JSON->State
      - RC=0 / RC=10 / FAIL
      - minimal logs, parse-fähig
      - stats: currentBalance (closest-to-today) + lastPeriodFrom/To
- [ ] Worker 2: State->Reports
      - liefert parsbare Logline für „month=YYYY-MM rows=N“
- [ ] Trigger (launchd):
      - startet nur, wenn PDF wirklich da ist
      - CR endet immer rc=0 (launchd schweigt)
      - Unerwartetes -> FAIL Noti

ENDE.