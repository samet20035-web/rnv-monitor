import os
import json
from datetime import datetime
from collections import defaultdict

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://fahrerauskunft.rnv-online.de/WebComm"
LOGIN_URL = f"{BASE_URL}/default.aspx"
ROSTER_URL = f"{BASE_URL}/roster.aspx"
START_URL = f"{LOGIN_URL}?TestingCookie=1"

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(BASE_PATH, "checkpoint.json")
NOTES_DIR = os.path.join(BASE_PATH, "notes")

WOCHENTAG_KURZ = {
    0: "Mo",
    1: "Di",
    2: "Mi",
    3: "Do",
    4: "Fr",
    5: "Sa",
    6: "So",
}

STOP_MAP = {
    "Bth. HD Betriebshof": "BHBE",
    "Bth HD Betriebshof": "BHBE",
    "Betriebshof": "BHBH",
    "Bismarckplatz": "BHBP",
    "Hauptbahnhof": "BHHF",
    "Rohrbach Süd": "RSRS",
    "Kirchheim Friedhof": "KHFH",
    "Leimen Friedhof": "LHFH",
    "Kirchheimer Straße": "EHKS",
    "Hans-Thoma-Platz": "HHHT",
    "Heiligenbergschule": "HHHS",
}

SPECIAL_START_CODES = {"BHBH", "BHBE"}
KEY_END_CODES = {"BHBP", "BHHF", "RSRS", "KHFH", "LHFH", "EHKS", "HHHT", "HHHS", "BHBH", "BHBE"}


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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Origin": "https://fahrerauskunft.rnv-online.de",
        "Referer": LOGIN_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    session.get(START_URL, headers=headers)
    r = session.get(LOGIN_URL, headers=headers)
    hidden = get_hidden_fields(r.text)

    payload = {
        **hidden,
        "__EVENTTARGET": "ctl00$cntMainBody$lgnView$lgnLogin$LoginButton",
        "ctl00$cntMainBody$lgnView$lgnLogin$UserName": username,
        "ctl00$cntMainBody$lgnView$lgnLogin$Password": password,
    }

    r2 = session.post(LOGIN_URL, data=payload, headers=headers)

    if r2.status_code == 500:
        raise Exception("RNV hat mit 500 geantwortet.")

    if not any(x in r2.text.lower() for x in ["logout", "abmelden", "dienstplan"]):
        raise Exception("Login fehlgeschlagen.")


def code_stop(name: str) -> str:
    raw = (name or "").replace("\xa0", " ").strip()

    if not raw:
        return ""

    for needle, code in STOP_MAP.items():
        if needle in raw:
            return code

    return raw


def is_service_row(row: dict) -> bool:
    art = (row["art"] or "").lower()
    line = (row["line"] or "").strip()

    if "pause" in art:
        return False
    if "wegezeit" in art:
        return False
    if not line.isdigit():
        return False

    return True


def parse_shift_rows(session: requests.Session, date_str: str, service_id: str):
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

        cells = [td.get_text(" ", strip=True).replace("\xa0", " ").strip() for td in tds]

        if not cells[0] or cells[0] != service_id:
            continue

        rows.append({
            "dienst": cells[0],
            "start_time": cells[1],
            "start_stop": cells[2],
            "end_time": cells[3],
            "end_stop": cells[4],
            "line": cells[6],
            "umlauf": cells[8],
            "art": cells[9],
        })

    return rows


def split_segments(rows: list[dict]) -> list[list[dict]]:
    segments = []
    current = []

    for row in rows:
        if is_service_row(row):
            current.append(row)
        else:
            if current:
                segments.append(current)
                current = []

    if current:
        segments.append(current)

    return segments


def choose_display_point(row: dict, is_first_in_segment: bool) -> tuple[str, str]:
    """
    Rückgabe:
    - Haltestellenkürzel
    - Uhrzeit
    """
    start_code = code_stop(row["start_stop"])
    end_code = code_stop(row["end_stop"])

    # Deine gewünschte Logik:
    # - Wenn Start/Betriebshof-Ausgang: Start zeigen
    # - sonst, wenn Ziel ein wichtiger Punkt ist: Ziel zeigen
    # - sonst Start zeigen
    if start_code in SPECIAL_START_CODES:
        return start_code, row["start_time"]

    if end_code in KEY_END_CODES:
        return end_code, row["end_time"]

    return start_code, row["start_time"]


def format_day_file(date_obj: datetime, dienst: str, rows: list[dict]) -> str:
    wd = WOCHENTAG_KURZ[date_obj.weekday()]
    header = f"{wd}, {date_obj.strftime('%d.%m.%y')}   {dienst}"

    output = [header, ""]

    segments = split_segments(rows)
    last_umlauf = None

    for seg in segments:
        if not seg:
            continue

        # Nur der erste und letzte sinnvolle Punkt pro Segment
        picked = [seg[0]]
        if len(seg) > 1 and seg[-1] != seg[0]:
            picked.append(seg[-1])

        for row in picked:
            stop_code, time_value = choose_display_point(row, row == seg[0])
            line = (row["line"] or "").strip()
            end_code = code_stop(row["end_stop"])
            umlauf = (row["umlauf"] or "").strip()

            if not line:
                continue

            output.append(f"{stop_code}  {time_value}  {line} {end_code}")

            if umlauf and umlauf != last_umlauf:
                output.append(f"       => {umlauf}")
                last_umlauf = umlauf

            output.append("")

    return "\n".join(output).rstrip() + "\n"


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

    # Gruppe pro Datum + Dienstnummer
    grouped = defaultdict(list)
    for s in services:
        key = f"{s['year']}-{s['month']}-{s['day']}-{s['id']}"
        grouped[key].append(s)

    for key, group in grouped.items():
        s = group[0]
        year = int(s["year"])
        month = int(s["month"])
        day = int(s["day"])
        dienst = s["id"]

        date_obj = datetime(year, month, day)
        date_str = date_obj.strftime("%Y-%m-%d")

        rows = parse_shift_rows(session, date_str, dienst)
        if not rows:
            print(f"Keine Daten für {date_str} / {dienst}")
            continue

        content = format_day_file(date_obj, dienst, rows)

        filename = f"{WOCHENTAG_KURZ[date_obj.weekday()]}_{date_obj.strftime('%d-%m-%y')}_{dienst}.txt"
        out_path = os.path.join(NOTES_DIR, filename)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"Geschrieben: {out_path}")


if __name__ == "__main__":
    main()
