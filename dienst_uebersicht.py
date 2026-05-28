import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# ── Konfiguration (identisch zu monitor.py, damit Secrets wiederverwendet werden) ──
BASE_URL    = "https://fahrerauskunft.rnv-online.de/WebComm"
LOGIN_URL   = f"{BASE_URL}/default.aspx"
ROSTER_URL  = f"{BASE_URL}/roster.aspx"
START_URL   = f"{LOGIN_URL}?TestingCookie=1"

USERNAME  = os.getenv("RNV_USER", "")
PASSWORD  = os.getenv("RNV_PASS", "")
MEIN_NAME = "Samet"

BASE_PATH        = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE  = os.path.join(BASE_PATH, "checkpoint.json")   # wird von monitor.py geschrieben
OUTPUT_MD        = os.path.join(BASE_PATH, "dienst_uebersicht.md")
OUTPUT_TXT       = os.path.join(BASE_PATH, "dienst_uebersicht.txt")

WOCHENTAG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WOCHENTAG_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# ── Haltestellenkürzel → Name ──────────────────────────────────────────────────
STOPS = {
    "BHBE": "Bth. HD Bergheim",    "BHBP": "Bismarckplatz",
    "BHBH": "Betriebshof",         "KHFH": "Kirchheim Friedhof",
    "HHHS": "Heiligenbergschule",  "HHHT": "Hans-Thoma-Platz",
    "RSRS": "Rohrbach Süd",        "BHHF": "HD Hauptbahnhof",
    "BHCA": "Campus Bergheim",     "BHWI": "Bth. Wieblinger Weg",
    "WSBF": "S-Bhf Weststadt/Südstadt",
    "NFCN": "Campus Im Neuenheimer Feld",
    "NFZO": "Zoo",                 "NFSB": "Schwimmbad",
    "NFKO": "Kopfklinik",          "NFJH": "Jugendherberge",
    "SBBF": "S-Bhf Schlierbach/Ziegelhausen",
    "SBOK": "S-Bhf Orthopädie",    "KHBF": "S-Bhf Kirchheim/Rohrbach",
    "KHRH": "Kirchheim Rathaus",   "KHKH": "Kirchheimer Hof",
    "KHHS": "Hagellachstraße",     "EHKS": "Kirchheimer Straße",
    "HHBG": "Heiligenberg",        "HHHB": "Heiligenbergstraße",
    "HHJF": "Johann-Fischer-Str.", "HHTG": "Tiefburg",
    "HHTB": "Turnerbrunnen",       "HHMS": "Mühltalstraße",
    "RBMA": "Rohrbach Markt",      "RBKI": "Rohrbach Kirche",
    "RBFR": "Rohrbach Friedhof",   "RBRH": "Rohrbach Rathaus",
    "RBNV": "Rohrbach NVZ",        "RBSP": "Sickingenplatz",
    "ASAB": "Alte Brücke",         "ASEP": "Friedrich-Ebert-Platz",
    "ASPK": "Peterskirche",        "ASRB": "Rathaus/Bergbahn",
    "ASSH": "Stadthalle",          "ASUP": "Universitätsplatz",
    "ASBF": "S-Bhf Altstadt",      "NHBG": "Bunsengymnasium",
    "NHTH": "Theodor-Heuss-Brücke","NHTP": "Technologiepark",
    "SRBF": "Schriesheim Bahnhof", "BSET": "Eppelheimer Terrasse",
    "SSET": "Eppelheimer Terrasse","SSMD": "Marlene-Dietrich-Platz",
    "SSMT": "Mark-Twain-Center",   "SSRS": "HD Rheinstraße",
    "LEFH": "Leimen Friedhof",     "LEGP": "Leimen Georgi-Marktplatz",
    "LEKC": "Leimen Kurpfalz-Centrum",
}

# Name → Kürzel (für HTML-Parsing)
STOPS_REV = {v.lower(): k for k, v in STOPS.items()}


# ── Wendelogik ─────────────────────────────────────────────────────────────────
def get_terminus(linie: str, nach_code: str, dow: int) -> str | None:
    """Gibt das Zielkürzel zurück, wohin der Zug nach dem Ausstieg weiterfährt."""
    mo_fr = 1 <= dow <= 5
    sa    = dow == 6

    if linie == "26":
        if mo_fr:
            if nach_code == "KHFH": return "HHHS"
            if nach_code == "HHHS": return "KHFH"
        if sa:
            if nach_code == "KHFH": return "HHHT"
            if nach_code == "HHHT": return "KHFH"

    if linie == "24" and mo_fr:
        if nach_code == "RSRS": return "HHHS"
        if nach_code == "HHHS": return "RSRS"

    if linie == "22":
        if nach_code in ("EHKS", "BSET", "SSET", "EHRH", "EHHS"): return "BHBP"
        if nach_code in ("BHBP", "BHHF", "WSBF"):                  return "EHKS"

    if linie == "21":
        if nach_code in ("HHHT", "SRBF"): return "BHBP"
        if nach_code == "BHBP":           return "HHHT"

    if linie == "23":
        if nach_code == "BHBP": return "LEFH"
        if nach_code == "LEFH": return "BHBP"

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


# ── Name → Kürzel ──────────────────────────────────────────────────────────────
def name_to_code(name: str) -> str:
    """Versucht einen Haltestellennamen in ein 4-stelliges Kürzel umzuwandeln."""
    if not name or not name.strip():
        return "????"
    n = name.strip()
    # direkte Suche im Reverse-Dict
    code = STOPS_REV.get(n.lower())
    if code:
        return code
    # Fallback: ersten 4 Buchstaben großgeschrieben
    letters = "".join(c for c in n.upper() if c.isalpha())
    return letters[:4] if len(letters) >= 4 else letters.ljust(4, "?")


# ── HTML-Tabelle parsen ────────────────────────────────────────────────────────
def parse_shift_html(html: str, date_str: str, dienst_id: str) -> list[dict]:
    """
    Parst die shift.aspx-HTML-Tabelle und gibt eine Liste von Blöcken zurück:
      - {"type": "fahrt",   "von": CODE, "zeit": "HH:MM", "nach": CODE, "linie": "26", "umlauf": "2657"}
      - {"type": "pause",   "von": "HH:MM", "bis": "HH:MM", "ort": NAME, "art": "Pause Unbezahlt"}
      - {"type": "umlauf",  "nr": "2657"}
    """
    soup = BeautifulSoup(html, "html.parser")
    tbl  = soup.find("table", id="ctl00_cntMainBody_lstDienstinfo")
    if not tbl:
        return []

    rows = tbl.find_all("tr")
    segments = []

    for row in rows:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 10:
            continue
        # Leerzeilen überspringen
        if not cells[0] or cells[0] == "\xa0":
            continue
        # Nur Zeilen des gesuchten Dienstes
        if cells[0] != dienst_id:
            continue

        segments.append({
            "dienst":  cells[0],
            "von_zeit": cells[1],
            "von_ort":  cells[2],
            "bis_zeit": cells[3],
            "bis_ort":  cells[4],
            "linie":    cells[6],
            "umlauf":   cells[8],
            "art":      cells[9],
        })

    if not segments:
        return []

    blocks      = []
    last_umlauf = None

    for seg in segments:
        art = seg["art"].lower()

        # ── Pause ──
        if "pause" in art:
            blocks.append({
                "type": "pause",
                "von":  seg["von_zeit"],
                "bis":  seg["bis_zeit"],
                "ort":  seg["von_ort"],
                "art":  seg["art"],
            })
            continue

        # ── Lenkzeit = eigentliche Fahrt ──
        if "lenkzeit" in art:
            uml = seg["umlauf"]
            if uml and uml != last_umlauf and last_umlauf is not None:
                blocks.append({"type": "umlauf", "nr": uml})
            last_umlauf = last_umlauf or uml

            von_code  = name_to_code(seg["von_ort"])
            nach_code = name_to_code(seg["bis_ort"])
            blocks.append({
                "type":   "fahrt",
                "von":    von_code,
                "zeit":   seg["von_zeit"],
                "bis":    seg["bis_zeit"],
                "nach":   nach_code,
                "linie":  seg["linie"],
                "umlauf": uml,
            })

    return blocks


# ── Einen Tag abrufen ──────────────────────────────────────────────────────────
def fetch_shift_blocks(session: requests.Session, date_str: str, dienst_id: str) -> list[dict]:
    """Ruft shift.aspx für ein Datum ab und gibt geparste Blöcke zurück."""
    # Calendar-Navigation simulieren (wie monitor.py)
    session.post(ROSTER_URL, data={
        "__EVENTTARGET":   "ctl00$cntMainBody$calRoster",
        "__EVENTARGUMENT": date_str,
    })
    resp = session.get(f"{BASE_URL}/shift.aspx?{date_str}")
    return parse_shift_html(resp.text, date_str, dienst_id)


# ── Kompakte Übersichtszeilen bauen ───────────────────────────────────────────
def blocks_to_lines(blocks: list[dict], dow: int) -> list[str]:
    """
    Wandelt Blöcke in Übersichtszeilen um:
      BHBE  07:41  26  KHFH  →  HHHS
            => 2657
      BHBP  11:55  26  KHFH  →  HHHS
    """
    lines    = []
    prev_nach = None

    for b in blocks:
        if b["type"] == "umlauf":
            lines.append(f"      => {b['nr']}")

        elif b["type"] == "pause":
            bezahlt = "bez." if "bezahlt" in b["art"].lower() and "unbezahlt" not in b["art"].lower() else "unbez."
            lines.append(f"  [ Pause {bezahlt}  {b['von']}–{b['bis']} ]")

        elif b["type"] == "fahrt":
            # Lücke markieren wenn Übergabe an anderem Ort
            if prev_nach and prev_nach != b["von"]:
                lines.append("")

            terminus     = get_terminus(b["linie"], b["nach"], dow)
            terminus_str = f"  →  {terminus}" if terminus else ""
            lines.append(
                f"{b['von']:<6}{b['zeit']}  {b['linie']:>2}  {b['nach']}{terminus_str}"
            )
            prev_nach = b["nach"]

    return lines


# ── Markdown-Ausgabe ───────────────────────────────────────────────────────────
def build_markdown(all_dienste: list[dict]) -> str:
    now = datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")
    lines = [
        f"# Dienstübersicht – {MEIN_NAME}",
        f"*Zuletzt aktualisiert: {now}*",
        "",
    ]

    for d in all_dienste:
        date_obj = datetime(int(d["year"]), int(d["month"]), int(d["day"]))
        wt       = WOCHENTAG[date_obj.weekday()]
        wt_kurz  = WOCHENTAG_KURZ[date_obj.weekday()]
        datum    = f"{int(d['day']):02d}.{int(d['month']):02d}.{d['year'][-2:]}"
        dow      = date_obj.weekday()  # 0=Mo … 6=So

        lines.append(f"## {wt}, {datum}  ·  Dienst {d['id']}")
        lines.append("")
        lines.append("```")

        header = f"{wt_kurz}, {datum}   {d['id']}"
        lines.append(header)
        lines.append("─" * max(len(header), 28))

        if d.get("blocks"):
            fahrt_lines = blocks_to_lines(d["blocks"], dow)
            lines.extend(fahrt_lines)

            # Dienstzeit berechnen
            fahrten = [b for b in d["blocks"] if b["type"] == "fahrt"]
            if fahrten:
                start = fahrten[0]["zeit"]
                ende  = fahrten[-1]["bis"]
                sh, sm = map(int, start.split(":"))
                eh, em = map(int, ende.split(":"))
                mins   = (eh * 60 + em) - (sh * 60 + sm)
                if mins < 0:
                    mins += 24 * 60
                h, m = divmod(mins, 60)
                lines.append("─" * 28)
                lines.append(f"{start} – {ende}  ({h}h{m:02d}min)")
        else:
            lines.append("(keine Fahrten gefunden)")

        lines.append("```")
        lines.append("")

    return "\n".join(lines)


# ── Plaintext-Ausgabe (für Notizen / Apple Watch) ─────────────────────────────
def build_txt(all_dienste: list[dict]) -> str:
    blocks_out = []

    for d in all_dienste:
        date_obj = datetime(int(d["year"]), int(d["month"]), int(d["day"]))
        wt_kurz  = WOCHENTAG_KURZ[date_obj.weekday()]
        datum    = f"{int(d['day']):02d}.{int(d['month']):02d}.{d['year'][-2:]}"
        dow      = date_obj.weekday()

        header = f"{wt_kurz}, {datum}   {d['id']}"
        entry  = [header, "─" * max(len(header), 28)]

        if d.get("blocks"):
            entry.extend(blocks_to_lines(d["blocks"], dow))

            fahrten = [b for b in d["blocks"] if b["type"] == "fahrt"]
            if fahrten:
                start = fahrten[0]["zeit"]
                ende  = fahrten[-1]["bis"]
                sh, sm = map(int, start.split(":"))
                eh, em = map(int, ende.split(":"))
                mins   = (eh * 60 + em) - (sh * 60 + sm)
                if mins < 0:
                    mins += 24 * 60
                h, m = divmod(mins, 60)
                entry.append("─" * 28)
                entry.append(f"{start} – {ende}  ({h}h{m:02d}min)")
        else:
            entry.append("(keine Fahrten)")

        blocks_out.append("\n".join(entry))

    return "\n\n\n".join(blocks_out)


# ── Hauptprogramm ──────────────────────────────────────────────────────────────
def main():
    # 1. checkpoint.json lesen (von monitor.py geschrieben)
    if not os.path.exists(CHECKPOINT_FILE):
        print("checkpoint.json nicht gefunden – monitor.py noch nicht gelaufen?")
        return

    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
        try:
            dienste = json.load(f)
        except (json.JSONDecodeError, ValueError):
            print("Fehler: checkpoint.json ist beschädigt.")
            return

    if not dienste:
        print("Keine Dienste in checkpoint.json.")
        return

    # Aufsteigend nach Datum sortieren
    dienste.sort(key=lambda x: (x.get("year", ""), x.get("month", ""), x.get("day", "").zfill(2)))

    # 2. Einloggen
    session = requests.Session()
    try:
        login(session)
        print("Login erfolgreich.")
    except RuntimeError as e:
        print(f"Login-Fehler: {e}")
        return

    # 3. Für jeden Dienst Schichtdetails abrufen
    for d in dienste:
        date_str = f"{d['year']}-{d['month'].zfill(2)}-{d['day'].zfill(2)}"
        print(f"  Abruf: {date_str}  Dienst {d['id']} …", end=" ")
        try:
            blocks = fetch_shift_blocks(session, date_str, d["id"])
            d["blocks"] = blocks
            print(f"{len([b for b in blocks if b['type']=='fahrt'])} Fahrten")
        except Exception as e:
            d["blocks"] = []
            print(f"Fehler: {e}")

    # 4. Ausgabe schreiben
    md_content  = build_markdown(dienste)
    txt_content = build_txt(dienste)

    with open(OUTPUT_MD,  "w", encoding="utf-8") as f:
        f.write(md_content)
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.write(txt_content)

    print(f"\nFertig:")
    print(f"  {OUTPUT_MD}")
    print(f"  {OUTPUT_TXT}")


if __name__ == "__main__":
    main()
