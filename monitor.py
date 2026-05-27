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
    headers = {"User-Agent": "Mozilla/5.0"}
    
    # 1. Login-Seite abrufen
    r = session.get(LOGIN_URL, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    # --- DEBUG: Hier siehst du im Log, welche Feldnamen existieren ---
    print("--- Gefundene Eingabefelder ---")
    for input_tag in soup.find_all("input"):
        print(f"Name: {input_tag.get('name')}, Type: {input_tag.get('type')}")
    print("-------------------------------")
    # --------------------------------------------------------------

    # 2. Felder suchen (wir nutzen .find mit einer kleinen Fehlerprüfung)
    def get_input(name):
        tag = soup.find("input", {"name": name})
        return tag["value"] if tag and tag.has_attr("value") else ""

    payload = {
        "__VIEWSTATE": get_input("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": get_input("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": get_input("__EVENTVALIDATION"),
        # Hier die exakten Namen aus deinem Log:
        "ctl00$cntMainBody$lgnView$lgnLogin$UserName": USERNAME, 
        "ctl00$cntMainBody$lgnView$lgnLogin$Password": PASSWORD,
        "ctl00$cntMainBody$lgnView$lgnLogin$LoginButton": "Anmelden", # Falls "Anmelden" nicht geht, versuche "Login"
    }

    # 3. Einloggen
    r2 = session.post(LOGIN_URL, data=payload, headers=headers)
    
    # DEBUG: Wenn Login fehlschlägt, geben wir den Inhalt der Seite aus
    if "logout" not in r2.text.lower() and "abmelden" not in r2.text.lower():
        print("Login fehlgeschlagen. HTML-Antwort der Login-Seite:")
        print(r2.text[:1000]) # Zeige die ersten 1000 Zeichen
        raise Exception("Login fehlgeschlagen - Feldnamen im Log prüfen!")

    print("Login erfolgreich!")

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

def main():
    session = requests.Session()
    login(session)
    html = session.get(BASE_URL).text
    current = parse_services(html)
    print(f"Gefundene Dienste: {current}")

if __name__ == "__main__":
    main()
