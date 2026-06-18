"""
Dienst-Übersicht Generator für RNV WebComm
Erstellt pro Dienst eine eigene .txt-Datei unter dienste/YYYY-MM-DD_DIENSTNR.txt

Format je Datei:
  Fr, 29.05.26   2061036
  ────────────────────────────
  BHBE  06:07  24  HHHS
        => 2662
  BHBH  09:53  24  RSRS

  BHBH  10:51  24  HHHS
        => 2663
  BHBH  13:21  26  KHFH
  ...
  ────────────────────────────
  06:07 – 15:03  (8h56min)

Logik:
  - Wendezeit → ignorieren
  - Pro Umlauf: erste Lenkzeit = Ausrücken/Start, letzte Lenkzeit = Einrücken/Ende
  - Umlaufwechsel → "      => UMLAUFNR" nach der ersten Zeile des Umlauts
  - Pause → Leerzeile zwischen den Umlauf-Blöcken (Pause selbst nicht anzeigen)
  - Nur Dienste in der Zukunft (ab heute) werden verarbeitet
  - Jede separate .txt-Datei pro Dienst im Ordner "dienste/"
"""

import os
import re
import json
import urllib.parse
import requests
import time as time_mod
from bs4 import BeautifulSoup
from datetime import datetime, date

# ── Konfiguration ─────────────────────────────────────────────────────────────
BASE_URL   = "https://fahrerauskunft.rnv-online.de/WebComm"
LOGIN_URL  = f"{BASE_URL}/default.aspx"
ROSTER_URL = f"{BASE_URL}/roster.aspx"
START_URL  = f"{LOGIN_URL}?TestingCookie=1"

USERNAME   = os.getenv("RNV_USER", "")
PASSWORD   = os.getenv("RNV_PASS", "")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
MEIN_NAME  = "Samet"

BASE_PATH       = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(BASE_PATH, "checkpoint.json")
ICLOUD_NOTES_URL = os.getenv(
    "ICLOUD_NOTES_URL",
    "https://www.icloud.com/notes/05dCvnyOenXtYy9Rkdt2T6w7w",
)
NOTES_SHORTCUT_NAME = os.getenv("NOTES_SHORTCUT_NAME", "DienstplanSpeichern")
MAX_SHORTCUT_TEXT_CHARS = int(os.getenv("MAX_SHORTCUT_TEXT_CHARS", "6000"))
OUTPUT_DIR      = os.path.join(BASE_PATH, "dienste")   # ← ein Ordner, viele Dateien

WOCHENTAG_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# ── Haltestellenkürzel ─────────────────────────────────────────────────────────
STOPS = {
    "Bth. HD Bergheim":             "BHBE",
    "Bth HD Bergheim":              "BHBE",
    "Bismarckplatz":                "BHBP",
    "Betriebshof":                  "BHBH",
    "Bth. HD Betriebshof":          "BHBH",
    "Bth HD Betriebshof":           "BHBH",
    "Kirchheim Friedhof":           "KHFH",
    "Heiligenbergschule":           "HHHS",
    "Hans-Thoma-Platz":             "HHHT",
    "Rohrbach Süd":                 "RSRS",
    "HD Hauptbahnhof":              "BHHF",
    "Campus Bergheim":              "BHCA",
    "Bth. Wieblinger Weg":          "BHWI",
    "S-Bhf Weststadt/Südstadt":     "WSBF",
    "Campus Im Neuenheimer Feld":   "NFCN",
    "Zoo":                          "NFZO",
    "Schwimmbad":                   "NFSB",
    "Kopfklinik":                   "NFKO",
    "Jugendherberge":               "NFJH",
    "S-Bhf Schlierbach/Ziegelhausen": "SBBF",
    "S-Bhf Orthopädie":             "SBOK",
    "S-Bhf Kirchheim/Rohrbach":     "KHBF",
    "Kirchheim Rathaus":            "KHRH",
    "Kirchheimer Hof":              "KHKH",
    "Hagellachstraße":              "KHHS",
    "Kirchheimer Straße":           "EHKS",
    "Heiligenberg":                 "HHBG",
    "Heiligenbergstraße":           "HHHB",
    "Johann-Fischer-Str.":          "HHJF",
    "Tiefburg":                     "HHTG",
    "Turnerbrunnen":                "HHTB",
    "Mühltalstraße":                "HHMS",
    "Rohrbach Markt":               "RBMA",
    "Rohrbach Kirche":              "RBKI",
    "Rohrbach Friedhof":            "RBFR",
    "Rohrbach Rathaus":             "RBRH",
    "Rohrbach NVZ":                 "RBNV",
    "Sickingenplatz":               "RBSP",
    "Alte Brücke":                  "ASAB",
    "Friedrich-Ebert-Platz":        "ASEP",
    "Peterskirche":                 "ASPK",
    "Rathaus/Bergbahn":             "ASRB",
    "Stadthalle":                   "ASSH",
    "Universitätsplatz":            "ASUP",
    "S-Bhf Altstadt":               "ASBF",
    "Bunsengymnasium":              "NHBG",
    "Theodor-Heuss-Brücke":         "NHTH",
    "Technologiepark":              "NHTP",
    "Schriesheim Bahnhof":          "SRBF",
    "Eppelheimer Terrasse":         "BSET",
    "Marlene-Dietrich-Platz":       "SSMD",
    "Mark-Twain-Center":            "SSMT",
    "HD Rheinstraße":               "SSRS",
    "Leimen Friedhof":              "LEFH",
    "Leimen Georgi-Marktplatz":     "LEGP",
    "Leimen Kurpfalz-Centrum":      "LEKC",
}


def ort_zu_kuerzel(name: str) -> str:
    """Wandelt Haltestellen-Klarnamen in 4-Zeichen-Kürzel um."""
    name = (name or "").strip()
    if not name or name == "\xa0":
        return "????"
    if name in STOPS:
        return STOPS[name]
    name_lower = name.lower()
    for key, code in STOPS.items():
        if key.lower() in name_lower or name_lower in key.lower():
            return code
    letters = "".join(c for c in name.upper() if c.isalpha())
    return letters[:4].ljust(4, "?") if letters else "????"


# ── Linien-Endstellen ──────────────────────────────────────────────────────────
ENDSTELLEN = {
    "21": {"mo_fr": ("HHHT", "SRBF"), "wende": ("HHHT", "BHBP")},
    "22": {"mo_fr": ("BHBP", "EHKS"), "wende": ("BHBP", "EHKS")},
    "23": {"mo_fr": ("BHBP", "LEFH"), "wende": ("BHBP", "LEFH")},
    "24": {"mo_fr": ("RSRS", "HHHS"), "wende": ("RSRS", "HHHS")},
    "26": {"mo_fr": ("KHFH", "HHHS"), "wende": ("KHFH", "HHHS")},
}


def gegenendstelle(linie: str, von_code: str, dow: int) -> str | None:
    info = ENDSTELLEN.get(linie)
    if not info:
        return None
    key  = "wende" if dow >= 5 else "mo_fr"
    a, b = info[key]
    if von_code == a:
        return b
    if von_code == b:
        return a
    return None


# ── Login ──────────────────────────────────────────────────────────────────────
def get_hidden_fields(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    return {
        inp.get("name"): inp.get("value", "")
        for inp in soup.find_all("input", type="hidden")
        if inp.get("name")
    }


def login(session: requests.Session):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Origin":       "https://fahrerauskunft.rnv-online.de",
        "Referer":      LOGIN_URL,
        "Accept":       "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    session.get(START_URL, headers=headers)
    r = session.get(LOGIN_URL, headers=headers)
    hidden = get_hidden_fields(r.text)
    payload = {
        **hidden,
        "__EVENTTARGET": "ctl00$cntMainBody$lgnView$lgnLogin$LoginButton",
        "ctl00$cntMainBody$lgnView$lgnLogin$UserName": USERNAME,
        "ctl00$cntMainBody$lgnView$lgnLogin$Password": PASSWORD,
    }
    r2 = session.post(LOGIN_URL, data=payload, headers=headers)
    if r2.status_code == 500:
        raise RuntimeError("Serverfehler 500")
    if not any(x in r2.text.lower() for x in ["logout", "abmelden", "dienstplan"]):
        raise RuntimeError("Login fehlgeschlagen")


# ── HTML parsen → Umlauf-Blöcke ───────────────────────────────────────────────
def parse_shift_zu_umlaeufe(html: str, dienst_id: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    tbl  = soup.find("table", id="ctl00_cntMainBody_lstDienstinfo")
    if not tbl:
        return []

    rows = []
    for tr in tbl.find_all("tr"):
        cells = [td.get_text(strip=True).replace("\xa0", "").strip()
                 for td in tr.find_all("td")]
        if len(cells) < 10:
            continue
        if cells[0] != dienst_id:
            continue
        rows.append({
            "von_zeit": cells[1],
            "von_ort":  cells[2],
            "bis_zeit": cells[3],
            "bis_ort":  cells[4],
            "linie":    cells[6],
            "umlauf":   cells[8],
            "art":      cells[9],
        })

    if not rows:
        return []

    umlaeufe: list[dict] = []
    aktueller_umlauf: str | None = None
    erste_fahrt: dict | None = None
    letzte_fahrt: dict | None = None

    def abschluss_umlauf(pause_danach: bool):
        nonlocal aktueller_umlauf, erste_fahrt, letzte_fahrt
        if aktueller_umlauf and erste_fahrt and letzte_fahrt:
            umlaeufe.append({
                "nr": aktueller_umlauf,
                "start": {
                    "zeit":      erste_fahrt["von_zeit"],
                    "von":       ort_zu_kuerzel(erste_fahrt["von_ort"]),
                    "linie":     erste_fahrt["linie"],
                    "nach_code": ort_zu_kuerzel(erste_fahrt["bis_ort"]),
                },
                "ende": {
                    "zeit":      letzte_fahrt["bis_zeit"],
                    "von":       ort_zu_kuerzel(letzte_fahrt["von_ort"]),
                    "bis":       ort_zu_kuerzel(letzte_fahrt["bis_ort"]),
                    "linie":     letzte_fahrt["linie"],
                    "nach_code": ort_zu_kuerzel(letzte_fahrt["von_ort"]),
                },
                "pause_danach": pause_danach,
            })
        aktueller_umlauf = None
        erste_fahrt      = None
        letzte_fahrt     = None

    for row in rows:
        art = row["art"].lower()

        if "wendezeit" in art:
            continue

        if "pause" in art:
            abschluss_umlauf(pause_danach=True)
            continue

        if "lenkzeit" in art:
            uml = row["umlauf"]

            if aktueller_umlauf and uml != aktueller_umlauf:
                abschluss_umlauf(pause_danach=False)

            if aktueller_umlauf is None:
                aktueller_umlauf = uml
                erste_fahrt      = row

            letzte_fahrt = row

    abschluss_umlauf(pause_danach=False)

    return umlaeufe


# ── Textdatei bauen ────────────────────────────────────────────────────────────
def umlaeufe_zu_text(dienst_id: str, date_str: str, umlaeufe: list[dict]) -> str:
    year, month, day = date_str.split("-")
    date_obj = date(int(year), int(month), int(day))
    dow      = date_obj.weekday()
    wt_kurz  = WOCHENTAG_KURZ[dow]
    datum    = f"{int(day):02d}.{int(month):02d}.{str(year)[-2:]}"

    trennlinie = "-" * 24
    header     = f"{wt_kurz}, {datum}   {dienst_id}"
    lines      = [header, trennlinie]

    for i, uml in enumerate(umlaeufe):
        s = uml["start"]
        e = uml["ende"]

        nach_start = s["nach_code"]

        nach_ende = gegenendstelle(e["linie"], e["nach_code"], dow)
        if nach_ende is None:
            nach_ende = e["bis"]

        lines.append(f"{s['von']:<6}{s['zeit']}  {s['linie']:>2}  {nach_start}")
        lines.append(f"      => {uml['nr']}")
        lines.append(f"{e['bis']:<6}{e['zeit']}  {e['linie']:>2}  {nach_ende}")

        if i < len(umlaeufe) - 1:
            lines.append("")

    if umlaeufe:
        start_zeit = umlaeufe[0]["start"]["zeit"]
        ende_zeit  = umlaeufe[-1]["ende"]["zeit"]
        sh, sm = map(int, start_zeit.split(":"))
        eh, em = map(int, ende_zeit.split(":"))
        mins   = (eh * 60 + em) - (sh * 60 + sm)
        if mins < 0:
            mins += 24 * 60
        h, m = divmod(mins, 60)
        lines.append(trennlinie)
        lines.append(f"{start_zeit} – {ende_zeit}  ({h}h{m:02d}min)")

    return "\n".join(lines)


# ── ntfy-Hilfsfunktionen ───────────────────────────────────────────────────────
def build_notes_shortcut_url(title: str, body: str, filename: str) -> str:
    note_text = body
    if MAX_SHORTCUT_TEXT_CHARS > 0 and len(note_text) > MAX_SHORTCUT_TEXT_CHARS:
        note_text = note_text[:MAX_SHORTCUT_TEXT_CHARS].rstrip()
        note_text += f"\n\n[Text gekuerzt. Komplette TXT-Datei: {filename}]"
    params = (
        f"name={urllib.parse.quote(NOTES_SHORTCUT_NAME, safe='')}"
        f"&input=text"
        f"&text={urllib.parse.quote(note_text, safe='')}"
    )
    return f"shortcuts://run-shortcut?{params}"


def build_ntfy_actions(title: str, body: str, filename: str) -> str:
    shortcut_url = build_notes_shortcut_url(title, body, filename)
    actions = [f"view, Notiz erstellen, {shortcut_url}"]
    if ICLOUD_NOTES_URL:
        actions.append(f"view, iCloud Notizen, {ICLOUD_NOTES_URL}")
    return "; ".join(actions)


# ── Hauptprogramm ──────────────────────────────────────────────────────────────
def main():
    # 1. checkpoint.json lesen (von monitor.py geschrieben, hier nur gelesen)
    if not os.path.exists(CHECKPOINT_FILE):
        print("❌ checkpoint.json nicht gefunden – monitor.py zuerst ausführen!")
        return

    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
        try:
            dienste = json.load(f)
        except (json.JSONDecodeError, ValueError):
            print("❌ checkpoint.json ist beschädigt.")
            return

    if not dienste:
        print("ℹ️  Keine Dienste in checkpoint.json.")
        return

    # Aufsteigend nach Datum sortieren
    dienste.sort(key=lambda x: (
        x.get("year", ""),
        x.get("month", "").zfill(2),
        x.get("day",   "").zfill(2),
    ))

    # ── Nur zukünftige Dienste (ab heute) verarbeiten ─────────────────────────
    heute = date.today()
    dienste_zukunft = [
        d for d in dienste
        if date(int(d["year"]), int(d["month"]), int(d["day"])) >= heute
    ]

    if not dienste_zukunft:
        print("ℹ️  Keine zukünftigen Dienste in checkpoint.json.")
        return

    uebersprungen = len(dienste) - len(dienste_zukunft)
    if uebersprungen:
        print(f"ℹ️  {uebersprungen} vergangene Dienste übersprungen.")
    print(f"📋 {len(dienste_zukunft)} Dienst(e) werden verarbeitet.")

    # Ausgabeordner anlegen
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 2. Login (3 Versuche)
    session = requests.Session()
    for attempt in range(1, 4):
        try:
            login(session)
            print("✅ Login erfolgreich")
            break
        except RuntimeError as e:
            print(f"⚠️  Login Versuch {attempt}/3: {e}")
            if attempt < 3:
                time_mod.sleep(5)
    else:
        print("❌ Login endgültig fehlgeschlagen")
        return

    # 3. Pro Dienst: HTML holen, parsen, Datei schreiben
    for d in dienste_zukunft:
        date_str  = f"{d['year']}-{d['month'].zfill(2)}-{d['day'].zfill(2)}"
        dienst_id = d["id"]

        print(f"  📋 {date_str}  Dienst {dienst_id} …", end=" ", flush=True)

        try:
            # Calendar-Navigation simulieren (wie monitor.py)
            session.post(ROSTER_URL, data={
                "__EVENTTARGET":   "ctl00$cntMainBody$calRoster",
                "__EVENTARGUMENT": date_str,
            })
            html = session.get(
                f"{BASE_URL}/shift.aspx?{date_str}", timeout=15
            ).text

            umlaeufe = parse_shift_zu_umlaeufe(html, dienst_id)

            if not umlaeufe:
                print("⚠️  keine Umläufe gefunden")
                continue

            year, month, day = date_str.split("-")
            datum   = f"{int(day):02d}.{int(month):02d}.{str(year)[-2:]}"

            inhalt    = umlaeufe_zu_text(dienst_id, date_str, umlaeufe)
            dateiname = f"{date_str}_{dienst_id}.txt"
            pfad      = os.path.join(OUTPUT_DIR, dateiname)

            with open(pfad, "w", encoding="utf-8") as f:
                f.write(inhalt)

            # Push-Benachrichtigung
            if NTFY_TOPIC:
                try:
                    note_title = f"Dienst {dienst_id} - {datum}"
                    requests.post(
                        f"https://ntfy.sh/{NTFY_TOPIC}",
                        data=inhalt.encode("utf-8"),
                        headers={
                            "Title":    note_title,
                            "Tags":     "calendar",
                            "Priority": "default",
                            "Actions":  build_ntfy_actions(note_title, inhalt, dateiname),
                        },
                        timeout=10,
                    )
                except Exception as ntfy_err:
                    print(f"⚠️  ntfy-Fehler: {ntfy_err}")

            print(f"✅  {len(umlaeufe)} Umläufe → {dateiname}")

        except Exception as e:
            print(f"❌  Fehler: {e}")

    print(f"\n✅ Fertig. Dateien liegen in: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
