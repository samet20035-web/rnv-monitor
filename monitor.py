import os
import requests
from bs4 import BeautifulSoup
import json
import urllib.parse

def create_calendar_link(service):
    # Hier nehmen wir an, dein 'time'-String sieht immer so aus: "08:30 - 16:45"
    start_zeit, ende_zeit = service['time'].split("-")
    start_zeit = start_zeit.strip().replace(":", "") + "00"
    ende_zeit = ende_zeit.strip().replace(":", "") + "00"
    
    # Datum festlegen (29.05.2026)
    datum = "20260529T" 
    
    title = f"Straßenbahn Dienst {service['id']} (Samet)"
    details = f"Beginn: {service['time'].split('-')[0].strip()}\\nEnde: {service['time'].split('-')[1].strip()}"
    
    base_url = "https://www.google.com/calendar/render?action=TEMPLATE"
    params = {
        "text": title,
        "dates": f"{datum}{start_zeit}Z/{datum}{ende_zeit}Z",
        "details": details,
        "location": "RNV Betriebshof"
    }
    return f"{base_url}&{urllib.parse.urlencode(params)}"

# Konfiguration
BASE_URL = "https://fahrerauskunft.rnv-online.de/WebComm/roster.aspx"
LOGIN_URL = "https://fahrerauskunft.rnv-online.de/WebComm/default.aspx"
NTFY_TOPIC = os.getenv("NTFY_TOPIC")
USERNAME = os.getenv("RNV_USER")
PASSWORD = os.getenv("RNV_PASS")

def login(session: requests.Session):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": LOGIN_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    # 1. Erst den GET Request machen, um Cookies und die aktuellen Viewstates zu laden
    r = session.get(LOGIN_URL, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    # Hilfsfunktion für die Viewstates
    def get_input(name):
        tag = soup.find("input", {"name": name})
        return tag["value"] if tag and tag.has_attr("value") else ""

    # 2. Den Payload präzise zusammenbauen
    payload = {
        "__LASTFOCUS": "",
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": get_input("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": get_input("__VIEWSTATEGENERATOR"),
        "__VIEWSTATEENCRYPTED": "",
        "__EVENTVALIDATION": get_input("__EVENTVALIDATION"),
        "ctl00$cntMainBody$lgnView$lgnLogin$UserName": USERNAME, 
        "ctl00$cntMainBody$lgnView$lgnLogin$Password": PASSWORD,
        "ctl00$cntMainBody$lgnView$lgnLogin$LoginButton": "Anmelden" # Wenn 'Anmelden' fehlschlägt, hier 'Login' versuchen
    }

    # 3. POST Request senden
    r2 = session.post(LOGIN_URL, data=payload, headers=headers)
    
    # Check ob wir eingeloggt sind
    if "logout" in r2.text.lower() or "abmelden" in r2.text.lower() or "Dienstplan" in r2.text:
        print("Login erfolgreich!")
    else:
        # Hier geben wir die Fehlermeldung präziser aus
        print(f"Login gescheitert. Status Code: {r2.status_code}")
        raise Exception("Login fehlgeschlagen - Server hat Zugriff verweigert.")

def parse_services(html: str):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "ctl00_ctl00_cntMainBody_calRoster"})
    services = []
    if not table: return services

    for td in table.find_all("td", {"class": "calDay"}):
        title = td.get("title", "")
        if "Dienst:" in title and "abwesend" not in title:
            strong = td.find("strong")
            day = strong.get_text(strip=True)[:2]
            span = td.find("span")
            time_val = span.get_text(strip=True) if span else ""
            dienst_id = title.split("Dienst:")[1].split("•")[0].strip()
            services.append({"day": day, "time": time_val, "id": dienst_id})
    return services

def format_message(change_type, service):
    # change_type ist z.B. "Neuer Dienst" oder "Dienständerung"
    # service ist das Dictionary mit den Daten
    msg = (f"🔔 {change_type}\n"
           f"📅 Tag: {service['day']}.05.2026\n"
           f"⏰ Zeit: {service['time']}\n"
           f"🆔 Dienstnummer: {service['id']}")
    return msg

def notify(service):
    if NTFY_TOPIC:
        link = create_calendar_link(service)
        msg = (f"🔔 Neuer Dienst\n"
               f"📅 Tag: {service['day']}.05.2026\n"
               f"⏰ Zeit: {service['time']}\n"
               f"🆔 Dienstnummer: {service['id']}\n\n"
               f"👉 Tippe auf die Nachricht, um den Dienst zum Kalender hinzuzufügen!")
        
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}", 
            data=msg.encode("utf-8"),
            headers={
                "Title": "Perdis",
                "Priority": "high",
                "Click": link  # <--- Das ist der "Knopf" (Tippen öffnet Kalender)
            }
        )
from datetime import datetime

def main():
    print("--- STARTE MONITOR ---")
    session = requests.Session()
    
    try:
        login(session)
        print("Login erfolgreich!")
        
        html = session.get(BASE_URL).text
        current = parse_services(html)
        print(f"DEBUG: Gefundene Dienste: {current}")
        
        old = []
        if os.path.exists("checkpoint.json"):
            with open("checkpoint.json", "r") as f:
                old = json.load(f)
        
        if current != old:
            print("Änderung erkannt!")
            for item in current:
                if item not in old:
                    notify(item)
                    print(f"Push gesendet für Dienst: {item['id']}")
            
            with open("checkpoint.json", "w") as f:
                json.dump(current, f, indent=2)
        else:
            print("Keine Änderungen.")
            
    except Exception as e:
        print(f"FEHLER: {e}")

if __name__ == "__main__":
    main()
