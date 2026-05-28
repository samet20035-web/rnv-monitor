import os
import json
from datetime import datetime

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://fahrerauskunft.rnv-online.de/WebComm"
CHECKPOINT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkpoint.json")
NOTES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes")

WOCHENTAG_KURZ = {
    0: "Mo",
    1: "Di",
    2: "Mi",
    3: "Do",
    4: "Fr",
    5: "Sa",
    6: "So",
}

LOCATION_CODES = [
    ("Bth. HD Betriebshof", "BHBE"),
    ("Bth HD Betriebshof", "BHBE"),
    ("Betriebshof", "BHBH"),
    ("Bismarckplatz", "BHBP"),
    ("Hauptbahnhof", "BHHF"),
    ("Rohrbach Süd", "RSRS"),
    ("Kirchheim Friedhof", "KHFH"),
    ("Leimen Friedhof", "LHFH"),
    ("Kirchheimer Straße", "EHKS"),
    ("Hans-Thoma-Platz", "HHHT"),
]

def load_checkpoint():
    if not os.path.exists(CHECKPOINT_FILE):
        return []
    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_hidden_fields(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    return {
        inp.get("name"): inp.get("value", "")
        for inp in soup.find_all("input", type="hidden")
        if inp.get("name")
    }

def login(session: requests.Session, username: str, password: str):
    login_url = f"{BASE_URL}/default.aspx"
    roster_url = f"{BASE_URL}/roster.aspx"
    start_url = f"{login_url}?TestingCookie=1"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Origin": "https://fahrerauskunft.rnv-online.de",
        "Referer": login_url,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    session.get(start_url, headers=headers)
    r = session.get(login_url, headers=headers)
    hidden = get_hidden_fields(r.text)

    payload = {
        **hidden,
        "__EVENTTARGET": "ctl00$cntMainBody$lgnView$lgnLogin$LoginButton",
        "ctl00$cntMainBody$lgnView$lgnLogin$UserName": username,
        "ctl00$cntMainBody$lgnView$lgnLogin$Password": password,
    }

    r2 = session.post(login_url, data=payload, headers=headers)

    if r2.status_code == 500:
        raise Exception("RNV hat mit 500 geantwortet.")

    if not any(x in r2.text.lower() for x in ["logout", "abmelden", "dienstplan"]):
        raise Exception("Login fehlgeschlagen.")

def abbrev_location(text: str, position: str = "") -> str:
    raw = (text or "").replace("\xa0", " ").strip()

    if not raw:
        return ""

    # Sonderfall Betriebshof HD
    if "Bth. HD Betriebshof" in raw or "Bth HD Betriebshof" in raw:
        return "BHBE" if position in ("start", "end") else "BHBH"

    for needle, code in LOCATION_CODES:
        if needle in raw:
            return code

    return raw

def parse_shift_rows(session: requests.Session, date_str: str, service_id: str):
    """
    Liest die Tagesseite und gibt alle Zeilen für genau diese Dienstnummer zurück.
    """
    resp = session.get(f"{BASE_URL}/shift.aspx?{date_str}")
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": "ctl00_cntMainBody_lstDienstinfo"})

    if not table:
        return []

    rows = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 10:
            continue

        vals = [td.get_text(" ", strip=True).replace("\xa0", "").strip() for td in tds]
        if vals[0] != service_id:
            continue

        rows.append({
            "dienst": vals[0],
            "von": vals[1],
            "start_ort": vals[2],
            "bis": vals[3],
            "end_ort": vals[4],
            "abw": vals[5],
            "linie": vals[6],
            "kurs": vals[7],
            "umlauf": vals[8],
            "art": vals[9],
        })

    return rows

def build_day_text(date_obj: datetime, service_id: str, rows: list[dict]) -> str:
    wd = WOCHENTAG_KURZ[date_obj.weekday()]
    header = f"{wd}, {date_obj.strftime('%d.%m.%y')}   {service_id}"
    lines = [header]

    current_umlauf = None

    for row in rows:
        art = (row["art"] or "").lower()
        start_code = abbrev_location(row["start_ort"], "start")
        end_code = abbrev_location(row["end_ort"], "end")
        von = row["von"]
        bis = row["bis"]
        linie = row["linie"]
        umlauf = row["umlauf"]

        # Pause-Zeilen separat oder überspringen
        if "pause" in art:
            # Wenn du Pause-Zeilen auch sehen willst, diese 2 Zeilen aktiv lassen:
            lines.append(f"       PAUSE {von} - {bis}")
            continue

        # Hauptzeile
        if linie and linie != "&nbsp;":
            main_line = f"{start_code}  {von}  {linie} {end_code}"
        else:
            main_line = f"{start_code}  {von}     {end_code}"

        lines.append(main_line)

        # Umlauf nur dann extra anzeigen, wenn er sich ändert
        if umlauf and umlauf != "&nbsp;" and umlauf != current_umlauf:
            lines.append(f"       => {umlauf}")
            current_umlauf = umlauf

        # Wegezeit / Mitfahrt markieren
        if "wegezeit" in art:
            if end_code:
                lines.append(f"       MITFAHRT {end_code}")

    return "\n".join(lines).rstrip() + "\n"

def main():
    username = os.getenv("RNV_USER", "").strip()
    password = os.getenv("RNV_PASS", "").strip()

    if not username or not password:
        raise RuntimeError("RNV_USER oder RNV_PASS fehlt.")

    os.makedirs(NOTES_DIR, exist_ok=True)

    services = load_checkpoint()
    if not services:
        print("Keine Dienste in checkpoint.json gefunden.")
        return

    session = requests.Session()
    login(session, username, password)

    grouped = {}
    for s in services:
        key = f"{s['year']}-{s['month']}-{s['day']}-{s['id']}"
        grouped[key] = s

    for s in grouped.values():
        year = int(s["year"])
        month = int(s["month"])
        day = int(s["day"])
        service_id = s["id"]

        date_obj = datetime(year, month, day)
        date_str = date_obj.strftime("%Y-%m-%d")

        rows = parse_shift_rows(session, date_str, service_id)
        if not rows:
            continue

        text = build_day_text(date_obj, service_id, rows)

        filename = f"{WOCHENTAG_KURZ[date_obj.weekday()]}_{date_obj.strftime('%d-%m-%y')}_{service_id}.txt"
        out_path = os.path.join(NOTES_DIR, filename)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)

        print(f"Geschrieben: {out_path}")

if __name__ == "__main__":
    main()
