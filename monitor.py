import os
import requests
from bs4 import BeautifulSoup
import json

# Konfiguration
BASE_URL = "https://fahrerauskunft.rnv-online.de/WebComm/roster.aspx"
LOGIN_URL = "https://fahrerauskunft.rnv-online.de/WebComm/default.aspx"
NTFY_TOPIC = os.getenv("NTFY_TOPIC")
USERNAME = os.getenv("RNV_USER")
PASSWORD = os.getenv("RNV_PASS")

def login(session: requests.Session):
    # ... (deine funktionierende login-Logik hier lassen) ...
    # Stelle sicher, dass hier "Login erfolgreich!" gedruckt wird
    pass 

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

def notify(message):
    if NTFY_TOPIC:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"))

def main():
    session = requests.Session()
    login(session)
    html = session.get(BASE_URL).text
    current = parse_services(html)
    
    # 1. Altes Ergebnis laden
    old = []
    if os.path.exists("checkpoint.json"):
        with open("checkpoint.json", "r") as f:
            try:
                old = json.load(f)
            except:
                old = []

    # 2. Vergleichen und speichern
    if current != old:
        print("Änderung erkannt!")
        if old: # Nur benachrichtigen, wenn schon ein alter Stand existierte
            notify("Dienstplan wurde aktualisiert.")
        
        with open("checkpoint.json", "w") as f:
            json.dump(current, f, indent=2)
    else:
        print("Keine Änderungen.")

if __name__ == "__main__":
    main()
