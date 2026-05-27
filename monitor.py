import os
import requests
from bs4 import BeautifulSoup
import json
import time

# Konfiguration (Wird aus Umgebungsvariablen geladen)
BASE_URL = "https://fahrerauskunft.rnv-online.de/WebComm/roster.aspx"
LOGIN_URL = "https://fahrerauskunft.rnv-online.de/WebComm/default.aspx"
NTFY_TOPIC = os.getenv("NTFY_TOPIC")
ICON_URL = "https://fahrerauskunft.rnv-online.de/WebComm/images/icons/ios80x80.png"

USERNAME = os.getenv("RNV_USER")
PASSWORD = os.getenv("RNV_PASS")

def login(session: requests.Session):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = session.get(LOGIN_URL, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    payload = {
        "__VIEWSTATE": soup.find("input", {"name": "__VIEWSTATE"})["value"],
        "__VIEWSTATEGENERATOR": soup.find("input", {"name": "__VIEWSTATEGENERATOR"})["value"],
        "__EVENTVALIDATION": soup.find("input", {"name": "__EVENTVALIDATION"})["value"],
        "ctl00$txtUsername": USERNAME,
        "ctl00$txtPassword": PASSWORD,
        "ctl00$btnLogin": "Login",
    }
    r2 = session.post(LOGIN_URL, data=payload, headers=headers)
    if "logout" not in r2.text.lower() and "abmelden" not in r2.text.lower():
        raise Exception("Login fehlgeschlagen")

def parse_services(html: str):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "ctl00_ctl00_cntMainBody_calRoster"})
    services = []
    if not table: return services

    for td in table.find_all("td", {"class": "calDay"}):
        title = td.get("title", "")
        if "Dienst:" in title and "abwesend" not in title:
            strong = td.find("strong")
            # Extrahiert nur die ersten 2 Ziffern (Datum)
            day = strong.get_text(strip=True)[:2]
            span = td.find("span")
            time_val = span.get_text(strip=True) if span else ""
            dienst_id = title.split("Dienst:")[1].split("•")[0].strip()

            services.append({"day": day, "time": time_val, "id": dienst_id})
    return services

def notify(message):
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"), 
                  headers={"Title": "RNV Dienstplan", "Priority": "high", "Tags": "calendar"})

def main():
    session = requests.Session()
    login(session)
    html = session.get(BASE_URL).text
    current = parse_services(html)

    old = []
    if os.path.exists("checkpoint.json"):
        with open("checkpoint.json", "r") as f:
            old = json.load(f)

    # Einfacher Vergleich: Wenn sich die Liste unterscheidet
    if current != old:
        # Hier könnte man detaillierter unterscheiden, bei Änderung einfach Nachricht:
        notify(f"Dienstplan aktualisiert! Anzahl Dienste: {len(current)}")
        with open("checkpoint.json", "w") as f:
            json.dump(current, f, indent=2)

if __name__ == "__main__":
    main()
