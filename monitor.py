import os
import requests
from bs4 import BeautifulSoup
import json
import urllib.parse
import time
from datetime import datetime

# --- KONFIGURATION ---
BASE_URL = "https://fahrerauskunft.rnv-online.de/WebComm"
LOGIN_URL = f"{BASE_URL}/default.aspx"
ROSTER_URL = f"{BASE_URL}/roster.aspx"
START_URL = f"{LOGIN_URL}?TestingCookie=1"

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "DEIN_TOPIC")
USERNAME = os.getenv("RNV_USER", "DEIN_USER")
PASSWORD = os.getenv("RNV_PASS", "DEIN_PASS")
MEIN_NAME = "Samet"

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(BASE_PATH, "checkpoint.json")

WOCHENTAG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

def get_hidden_fields(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    return {inp.get("name"): inp.get("value", "") for inp in soup.find_all("input", type="hidden") if inp.get("name")}

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

def create_calendar_link(service, details, date_str=None):
    try:
        if date_str is None:
            date_str = "2026-05-29"
        
        time_str = service['time'].strip()
        time_str = time_str.replace("–", "-").replace("—", "-")
        parts = time_str.split("-")
        if len(parts) < 2:
            return "https://google.com"
        
        start_time = parts[0].strip()
        end_time = parts[-1].strip()
        
        s_zeit = start_time.replace(":", "") + "00"
        e_zeit = end_time.replace(":", "") + "00"
        
        date_compact = date_str.replace("-", "")
        title = f"Straßenbahn Dienst {service['id']} ({MEIN_NAME})"
        
        params = {
            "text": title,
            "dates": f"{date_compact}T{s_zeit}/{date_compact}T{e_zeit}",
            "details": details,
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
        return "Details nicht verfügbar."

    rows = [r for r in table.find_all("tr") if len(r.find_all("td")) > 5]
    dienst_rows = [r for r in rows if r.find_all("td")[0].text.strip() == service_id]
    
    if not dienst_rows: 
        return "Keine Dienstdetails gefunden."

    start_row = dienst_rows[0]
    end_row = dienst_rows[-1]
    
    tds_start = start_row.find_all("td")
    tds_end = end_row.find_all("td")
    
    start_zeit = tds_start[1].text.strip() if len(tds_start) > 1 else "-"
    start_ort_raw = tds_start[2].text.strip() if len(tds_start) > 2 else "-"
    end_zeit = tds_end[3].text.strip() if len(tds_end) > 3 else "-"
    end_ort_raw = tds_end[4].text.strip() if len(tds_end) > 4 else "-"
    
    # Nur bei "Bth. Betriebshof" → (Ausrücken)/(Einrücken)
    def adapt_ort(ort, typ):
        if "Bth. Betriebshof" in ort or "Bth Betriebshof" in ort:
            if typ == "start":
                return "Betriebshof (Ausrücken)"
            else:
                return "Betriebshof (Einrücken)"
        return ort
    
    start_ort = adapt_ort(start_ort_raw, "start")
    end_ort = adapt_ort(end_ort_raw, "end")

    # ALLE Pausen sammeln (ohne Filter auf "bezahlte/unbezahlte")
    pausen = []
    for r in dienst_rows:
        tds = r.find_all("td")
        if len(tds) > 9:
            tätigkeits_art = tds[9].text.lower()
            # Nur isso: irgendeine Form von "Pause" enthalten
            if "pause" in tätigkeits_art:
                pause_von = tds[1].text.strip() if len(tds) > 1 else "-"
                pause_bis = tds[3].text.strip() if len(tds) > 3 else "-"
                pausen.append((pause_von, pause_bis))
    
    pausen_str = ""
    if pausen:
        for i, (von, bis) in enumerate(pausen, 1):
            pausen_str += f"{i}. Pause: {von} - {bis} Uhr\n"
        pausen_str = pausen_str.rstrip("\n")
    else:
        pausen_str = "Keine Pausen"

    return (f"Beginn: {start_zeit} Uhr ({start_ort})\n"
            f"{pausen_str}\n"
            f"Ende: {end_zeit} Uhr ({end_ort})")

def parse_services(html):
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
            services.append({"day": day_str, "time": time_val, "id": title.split("Dienst:")[1].split("•")[0].strip()})
    return services

def main():
    session = requests.Session()
    try:
        login(session)
        html = session.get(ROSTER_URL).text
        current = parse_services(html)
        
        old = []
        if os.path.exists(CHECKPOINT_FILE):
            try:
                with open(CHECKPOINT_FILE, "r") as f:
                    old = json.load(f)
            except (json.JSONDecodeError, ValueError):
                print("Warnung: Checkpoint-Datei war korrupt, erstelle neue Liste.")
                old = []
            
        if current != old:
            for item in current:
                if item not in old:
                    service_date = f"2026-05-{item['day']}"
                    
                    day_num = int(item['day'])
                    date_obj = datetime(2026, 5, day_num)
                    wochentag = WOCHENTAG[date_obj.weekday()]
                    
                    details = get_service_details(session, service_date, item['id'])
        
                    msg = (
                        f"Neuer Dienst {item['id']}\n"
                        f"📅 {wochentag}, {item['day']}.05.2026\n"
                        f"⏰ Zeit: {item['time']}\n"
                        f"🆔 Dienstnummer: {item['id']}\n\n"
                        f"👉 Tippe auf die Nachricht, um den Dienst zum Kalender hinzuzufügen!"
                    )
        
                    calendar_link = create_calendar_link(item, details, service_date)
                    headers = {
                        "Click": calendar_link,
                        "Title": "Perdis"
                    }
                    
                    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"), headers=headers)
                    print(f"Nachricht gesendet für Dienst {item['id']}")
            
            with open(CHECKPOINT_FILE, "w") as f:
                json.dump(current, f, indent=2)
            print("Checkpoint gespeichert.")
        else:
            print("Keine Änderungen.")
            
    except Exception as e:
        print(f"KRITISCHER FEHLER: {e}")

if __name__ == "__main__":
    main()
