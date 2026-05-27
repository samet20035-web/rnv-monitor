import os
import requests
from bs4 import BeautifulSoup
import json
import urllib.parse
import time

# --- KONFIGURATION ---
BASE_URL = "https://fahrerauskunft.rnv-online.de/WebComm"
LOGIN_URL = f"{BASE_URL}/default.aspx"
ROSTER_URL = f"{BASE_URL}/roster.aspx"
START_URL = f"{LOGIN_URL}?TestingCookie=1"

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "DEIN_TOPIC")
USERNAME = os.getenv("RNV_USER", "DEIN_USER")
PASSWORD = os.getenv("RNV_PASS", "DEIN_PASS")

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(BASE_PATH, "checkpoint.json")

def format_location(text):
    """Übersetzt RNV-Orte in das gewünschte Format für die Mutter."""
    text = text.replace("Bth. HD Bergheim", "Betriebshof")
    if "Betriebshof" in text:
        return f"{text} (Ausrücken/Einrücken)"
    return text

def create_calendar_link(service, details):
    """
    Erzeugt einen Link für den iPhone Kalender mit dem gewünschten Format.
    details: Ein String, den wir aus get_service_details erhalten.
    """
    # 1. Titel-Schema: Straßenbahn Dienst [Nummer] (Samet)
    title = f"Straßenbahn Dienst {service['id']} (Samet)"
    
    # 2. Uhrzeit extrahieren (Annahme: service['time'] ist "HH:MM-HH:MM")
    s, e = service['time'].split("-")
    s_zeit = s.strip().replace(":", "") + "00"
    e_zeit = e.strip().replace(":", "") + "00"
    
    # 3. Beschreibung: Stationen und Pausen
    # Wir nehmen die Details, die get_service_details liefert, und formatieren sie
    description = f"{details}" 
    
    params = {
        "text": title,
        "dates": f"20260529T{s_zeit}/20260529T{e_zeit}", # Datum muss ggf. dynamisch sein
        "details": description,
        "location": "RNV"
    }
    return f"https://www.google.com/calendar/render?action=TEMPLATE&{urllib.parse.urlencode(params)}"

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

def create_calendar_link(service):
    # Einfache Extraktion der Zeit (z.B. "07:51-12:11")
    try:
        s, e = service['time'].split("-")
        s_zeit = s.strip().replace(":", "") + "00"
        e_zeit = e.strip().replace(":", "") + "00"
        params = {
            "text": f"Dienst {service['id']}",
            "dates": f"20260529T{s_zeit}/20260529T{e_zeit}",
            "details": f"Dienstnummer: {service['id']}",
            "location": "RNV"
        }
        return f"https://www.google.com/calendar/render?action=TEMPLATE&{urllib.parse.urlencode(params)}"
    except:
        return "https://google.com"

def parse_services(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id=lambda x: x and "calRoster" in x)
    if not table: return []
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
        
        old = json.load(open(CHECKPOINT_FILE)) if os.path.exists(CHECKPOINT_FILE) else []
        
        if current != old:
            for item in current:
                if item not in old:
                    raw_details = get_service_details(session, "2026-05-29", item['id'])
                    clean_details = format_location(raw_details)
                    
                    msg = (
                        f"🔔 Neuer Dienst {item['id']}\n"
                        f"📅 Tag: {item['day']}.05.2026\n"
                        f"⏰ Zeit: {item['time']}\n"
                        f"🆔 Dienstnummer: {item['id']}\n\n"
                        f"👉 Tippe auf die Nachricht, um den Dienst zum Kalender hinzuzufügen!"
                    )
                    headers = {"Click": create_calendar_link(item, clean_details)}
                    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"), headers=headers)
            
            with open(CHECKPOINT_FILE, "w") as f:
                json.dump(current, f, indent=2)
    except Exception as e:
        print(f"KRITISCHER FEHLER: {e}")

if __name__ == "__main__":
    main()
