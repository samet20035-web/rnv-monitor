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

def get_hidden_fields(html: str) -> dict:
    """Extrahiert alle versteckten Felder (VIEWSTATE, EVENTVALIDATION, etc.)"""
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
    
    # 1. Cookie-Initialisierung
    session.get(START_URL, headers=headers)
    
    # 2. Login-Seite laden
    r = session.get(LOGIN_URL, headers=headers)
    hidden = get_hidden_fields(r.text)
    
    if "__VIEWSTATE" not in hidden:
        raise Exception("Login-Seite liefert kein __VIEWSTATE. Zugriff vermutlich blockiert.")

    # 3. Payload aufbauen
    payload = {
        **hidden,
        "__EVENTTARGET": "ctl00$cntMainBody$lgnView$lgnLogin$LoginButton",
        "ctl00$cntMainBody$lgnView$lgnLogin$UserName": USERNAME, 
        "ctl00$cntMainBody$lgnView$lgnLogin$Password": PASSWORD,
    }
    
    # 4. POST Request
    r2 = session.post(LOGIN_URL, data=payload, headers=headers)
    
    # Debugging bei Fehler
    with open(os.path.join(BASE_PATH, "debug_login.html"), "w", encoding="utf-8") as f:
        f.write(r2.text)
        
    if r2.status_code == 500:
        raise Exception("Serverfehler 500: Die RNV-Seite blockiert die Anfrage (IP-Sperre).")
    
    if not any(x in r2.text.lower() for x in ["logout", "abmelden", "dienstplan"]):
        raise Exception("Login fehlgeschlagen. Bitte Zugangsdaten in Secrets prüfen.")

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
        print("Login erfolgreich.")
        
        # Dienste abrufen
        html = session.get(ROSTER_URL).text
        current = parse_services(html)
        
        old = json.load(open(CHECKPOINT_FILE)) if os.path.exists(CHECKPOINT_FILE) else []
        
        if current != old:
            for item in current:
                if item not in old:
                    msg = f"🔔 Neuer Dienst {item['id']}\n📅 {item['day']}.05.2026\n⏰ {item['time']}"
                    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"))
            
            with open(CHECKPOINT_FILE, "w") as f:
                json.dump(current, f, indent=2)
            print("Änderungen gefunden und gemeldet.")
        else:
            print("Keine Änderungen.")
            
    except Exception as e:
        print(f"KRITISCHER FEHLER: {e}")

if __name__ == "__main__":
    main()
