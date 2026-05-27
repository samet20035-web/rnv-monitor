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

def notify(message):
    if NTFY_TOPIC:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"))

def main():
    session = requests.Session()
    login(session)
    html = session.get(BASE_URL).text
    current = parse_services(html)

    print(f"Gefundene Dienste: {current}") # Damit siehst du im Log, was er gefunden hat
    
    # --- TEST-TRIGGER FÜR PUSH ---
    # Entferne diese Zeile wieder, wenn du sie nicht mehr brauchst!
    notify(f"Test-Push: Gefunden wurden {len(current)} Dienste. Der erste ist: {current[0] if current else 'Keine'}")
    # -----------------------------

    old = []
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
