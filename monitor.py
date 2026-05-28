import os
import requests
from bs4 import BeautifulSoup
import json
import urllib.parse
from datetime import datetime, time, timedelta

BASE_URL = "https://fahrerauskunft.rnv-online.de/WebComm"
LOGIN_URL = f"{BASE_URL}/default.aspx"
ROSTER_URL = f"{BASE_URL}/roster.aspx"
START_URL = f"{LOGIN_URL}?TestingCookie=1"

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "DEIN_TOPIC")
NTFY_TOPIC_MAMA = os.getenv("NTFY_TOPIC_MAMA")
USERNAME = os.getenv("RNV_USER", "DEIN_USER")
PASSWORD = os.getenv("RNV_PASS", "DEIN_PASS")
MEIN_NAME = "Samet"

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(BASE_PATH, "checkpoint.json")
ICS_FILE = os.path.join(BASE_PATH, "dienstplan.ics")

WOCHENTAG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

def generate_ics(services, session):
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RNV//Dienstplan//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ]

    for s in services:
        # Dynamische Variablen aus dem Dienst-Objekt nutzen
        jahr = s.get('year', '2026')
        monat = s.get('month', '05')
        tag = s['day'].zfill(2) # Stellt sicher, dass aus '1' -> '01' wird
        
        # Abfrage-Datum für die Details (muss für die RNV Seite passen)
        date_str = f"{jahr}-{monat}-{tag}"
        info = get_service_details(session, date_str, s['id'])

        if info["start_time"] and info["start_time"] != "-":
            start_zeit = info["start_time"].replace(":", "") + "00"
            ende_zeit = info["end_time"].replace(":", "") + "00"
            desc = info["text"].replace(chr(10), "\\n")

            ics_lines.append("BEGIN:VEVENT")
            ics_lines.append(f"SUMMARY:Straßenbahn Dienst {s['id']} ({MEIN_NAME})")
            # Dynamische Datums-Zusammensetzung für den Kalender
            ics_lines.append(f"DTSTART:{jahr}{monat}{tag}T{start_zeit}")
            ics_lines.append(f"DTEND:{jahr}{monat}{tag}T{ende_zeit}")
            ics_lines.append(f"DESCRIPTION:{desc}")
            ics_lines.append("END:VEVENT")

    ics_lines.append("END:VCALENDAR")
    return "\n".join(ics_lines)
    
def get_hidden_fields(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    return {
        inp.get("name"): inp.get("value", "")
        for inp in soup.find_all("input", type="hidden")
        if inp.get("name")
    }

def login(session: requests.Session):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Origin": "https://fahrerauskunft.rnv-online.de",
        "Referer": LOGIN_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded"
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
        raise Exception("Serverfehler 500: RNV blockiert die Anfrage.")
    if not any(x in r2.text.lower() for x in ["logout", "abmelden", "dienstplan"]):
        raise Exception("Login fehlgeschlagen.")

def create_calendar_link(service, info, date_str=None):
    try:
        if date_str is None:
            date_str = "2026-05-29"

        start_time = info["start_time"]
        end_time = info["end_time"]
        if not start_time or not end_time or start_time == "-" or end_time == "-":
            return "https://google.com"

        start_compact = start_time.replace(":", "") + "00"
        end_compact = end_time.replace(":", "") + "00"
        date_compact = date_str.replace("-", "")
        title = f"Straßenbahn Dienst {service['id']} ({MEIN_NAME})"

        params = {
            "text": title,
            "dates": f"{date_compact}T{start_compact}/{date_compact}T{end_compact}",
            "details": info["text"],
            "location": "RNV"
        }
        return f"https://www.google.com/calendar/render?action=TEMPLATE&{urllib.parse.urlencode(params)}"
    except Exception as ex:
        print(f"Warnung: Kalenderlink konnte nicht erstellt werden: {ex}")
        return "https://google.com"

def get_service_details(session, date_str, service_id):
    session.get(ROSTER_URL)

    payload = {
        "__EVENTTARGET": "ctl00$cntMainBody$calRoster",
        "__EVENTARGUMENT": date_str
    }
    session.post(ROSTER_URL, data=payload)

    resp = session.get(f"{BASE_URL}/shift.aspx?{date_str}")
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": "ctl00_cntMainBody_lstDienstinfo"})

    if not table:
        return {
            "text": "Details nicht verfügbar.",
            "start_time": None,
            "end_time": None,
            "start_ort": None,
            "end_ort": None
        }

    rows = [r for r in table.find_all("tr") if len(r.find_all("td")) > 5]
    dienst_rows = [r for r in rows if r.find_all("td")[0].text.strip() == service_id]

    if not dienst_rows:
        return {
            "text": "Keine Dienstdetails gefunden.",
            "start_time": None,
            "end_time": None,
            "start_ort": None,
            "end_ort": None
        }

    def clean_ort(ort: str, typ: str) -> str:
        ort = (ort or "").strip()
        if "Bth. HD Betriebshof" in ort or "Bth HD Betriebshof" in ort:
            return "Betriebshof (Ausrücken)" if typ == "start" else "Betriebshof (Einrücken)"
        return ort

    def fmt_time(t: str) -> str:
        t = (t or "").strip()
        return t if t else "-"

    start_row = dienst_rows[0]
    end_row = dienst_rows[-1]

    tds_start = start_row.find_all("td")
    tds_end = end_row.find_all("td")

    start_time = tds_start[1].text.strip() if len(tds_start) > 1 else "-"
    start_ort_raw = tds_start[2].text.strip() if len(tds_start) > 2 else "-"
    end_time = tds_end[3].text.strip() if len(tds_end) > 3 else "-"
    end_ort_raw = tds_end[4].text.strip() if len(tds_end) > 4 else "-"

    start_ort = clean_ort(start_ort_raw, "start")
    end_ort = clean_ort(end_ort_raw, "end")

    pausen = []
    for r in dienst_rows:
        tds = r.find_all("td")
        if len(tds) > 9:
            art = tds[9].text.strip().lower()
            if "pause" in art:
                pause_von = tds[1].text.strip() if len(tds) > 1 else "-"
                pause_bis = tds[3].text.strip() if len(tds) > 3 else "-"
                pausen.append((pause_von, pause_bis))

    text_parts = [f"Beginn: {fmt_time(start_time)} Uhr ({start_ort})"]

    if pausen:
        for i, (von, bis) in enumerate(pausen, 1):
            text_parts.append(f"{i}. Pause: {von} - {bis} Uhr")
    else:
        text_parts.append("Keine Pausen")

    text_parts.append(f"Ende: {fmt_time(end_time)} Uhr ({end_ort})")

    return {
        "text": "\n".join(text_parts),
        "start_time": start_time,
        "end_time": end_time,
        "start_ort": start_ort,
        "end_ort": end_ort
    }

def parse_services(html, month, year):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id=lambda x: x and "calRoster" in x)
    if not table:
        return []

    services = []
    for td in table.find_all("td", {"class": "calDay"}):
        title = td.get("title", "")
        if "Dienst:" in title and "abwesend" not in title:
            day_str = td.find("strong").get_text(strip=True)[:2]
            span = td.find("span")
            time_val = span.get_text(strip=True) if span else ""
            
            # HIER werden Jahr und Monat ins Dictionary geschrieben:
            services.append({
                "day": day_str,
                "time": time_val,
                "id": title.split("Dienst:")[1].split("•")[0].strip(),
                "month": month,
                "year": year
            })
    return services

def main():
    now = datetime.utcnow().hour
    if not (6 <= now < 17):
        print("Außerhalb der Zeit. Skript pausiert.")
        return

    session = requests.Session()
    try:
        login(session)
       # 2. Dynamisch beide Monate laden
        all_services = []
        # WICHTIG: Hier jetzt die Parameter mitgeben!
        html_curr = session.get(ROSTER_URL).text
        all_services.extend(parse_services(html_curr, "05", "2026"))
        
        heute = datetime.utcnow()
        naechster_monat = (heute.replace(day=28) + timedelta(days=5)).replace(day=28)
        html_next = session.get(f"{ROSTER_URL}?{naechster_monat.strftime('%Y-%m-%d')}").text
        # WICHTIG: Hier jetzt die dynamischen Parameter für den nächsten Monat!
        all_services.extend(parse_services(html_next, naechster_monat.strftime("%m"), naechster_monat.strftime("%Y")))
        
        # 3. Dubletten entfernen (falls ein Dienst in beiden Monaten auftaucht)
        unique_services = {f"{s['day']}-{s['id']}": s for s in all_services}.values()
        current = list(unique_services)

        old = []
        if os.path.exists(CHECKPOINT_FILE):
            try:
                with open(CHECKPOINT_FILE, "r") as f:
                    old = json.load(f)
            except (json.JSONDecodeError, ValueError):
                print("Warnung: Checkpoint-Datei war korrupt, erstelle neue Liste.")
                old = []

        old_dict = {item["id"]: item for item in old}
        current_dict = {item["id"]: item for item in current}

        for item_id, item in current_dict.items():
            service_date = f"2026-05-{item['day']}"
            day_num = int(item["day"])
            date_obj = datetime(2026, 5, day_num)
            wochentag = WOCHENTAG[date_obj.weekday()]
            info = get_service_details(session, service_date, item["id"])

            if item_id not in old_dict:
                msg = (
                    f"Neuer Dienst {item['id']}\n"
                    f"📅 {wochentag}, {item['day']}.05.2026\n"
                    f"⏰ Zeit: {item['time']}\n"
                    f"🆔 Dienstnummer: {item['id']}\n\n"
                )

                requests.post(
                    f"https://ntfy.sh/{NTFY_TOPIC}",
                    data=msg.encode("utf-8"),
                    headers={"Title": "Perdis"}
                )

                msg_mama = (
                    f"Neuer Dienst hinzugefügt\n"
                    f"📅 Wann: {wochentag}, {item['day']}.05.2026\n"
                    f"⏰ Zeit: {item['time']}\n\n"
                    f"*Samets Dienstplan wurde aktualisiert.*"
                )

                print("NTFY_TOPIC_MAMA =", repr(NTFY_TOPIC_MAMA))

                resp = requests.post(
                    f"https://ntfy.sh/{NTFY_TOPIC_MAMA}",
                    data=msg_mama.encode("utf-8"),
                    headers={"Title": "Dienstplan Samet RNV"},
                    timeout=10,
                )
                
                print("ntfy status:", resp.status_code)
                print("ntfy body:", resp.text[:300])

            elif old_dict[item_id] != item:
                msg = (
                    f"🔔 Dienstplanänderung {item['id']}\n"
                    f"📅 {wochentag}, {item['day']}.05.2026\n"
                    f"⏰ Neue Zeit: {item['time']}\n"
                    f"🆔 Dienstnummer: {item['id']}\n\n"
                )

                requests.post(
                    f"https://ntfy.sh/{NTFY_TOPIC}",
                    data=msg.encode("utf-8"),
                    headers={"Title": "Perdis"}
                )

                msg_mama = (
                    f"⚠️ Samets Dienst hat sich geändert\n"
                    f"📅 Wann: {wochentag}, {item['day']}.05.2026\n"
                    f"⏰ Neue Zeit: {item['time']}\n\n"
                    f"*Der Dienstplan wurde angepasst. Bitte den Kalender prüfen.*"
                )

                requests.post(
                    f"https://ntfy.sh/{NTFY_TOPIC_MAMA}",
                    data=msg_mama.encode("utf-8"),
                    headers={"Title": "Dienstplan Samet RNV"}
                )

            else:
                continue

        ics_data = generate_ics(current, session)
        with open(ICS_FILE, "w", encoding="utf-8") as f:
            f.write(ics_data)
        print("ICS-Datei aktualisiert.")

        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(current, f, indent=2)
        print("Checkpoint gespeichert.")

    except Exception as e:
        print(f"KRITISCHER FEHLER: {e}")

if __name__ == "__main__":
    main()
