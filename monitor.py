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
            "details": details, # Hier die Pausen und Orte einfügen
            "location": "RNV"
        }
        return f"https://www.google.com/calendar/render?action=TEMPLATE&{urllib.parse.urlencode(params)}"
    except:
        return "https://google.com"
        
def get_service_details(session, date_str, service_id):
    # 1. Wir müssen erst die Roster-Seite "aufrufen", damit die Session weiß, 
    # dass wir in der Dienstplan-Ansicht sind.
    session.get(ROSTER_URL)
    
    # 2. Um den Tag/Dienst zu "klicken", müssen wir oft die hidden fields 
    # der Roster-Seite mitsenden, damit das System weiß, welcher Tag gemeint ist.
    # Da die RNV-Seite wahrscheinlich mit __EVENTTARGET arbeitet:
    # (Dies ist der Teil, der im Browser beim Klicken passiert)
    payload = {
        "__EVENTTARGET": "ctl00$cntMainBody$calRoster", # Das ist der Kalender-Control-Name
        "__EVENTARGUMENT": date_str,                   # Hier wird das Datum übergeben
        # Manchmal müssen hier noch andere __VIEWSTATE Felder mit, 
        # die wir von der Roster-Seite auslesen müssten.
    }
    
    # Klick simulieren
    session.post(ROSTER_URL, data=payload)
    
    # 3. Jetzt erst die Detailseite aufrufen
    resp = session.get(f"{BASE_URL}/shift.aspx")
    soup = BeautifulSoup(resp.text, "html.parser")
    resp = session.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": "ctl00_cntMainBody_lstDienstinfo"})
    if not table: return "Details nicht verfügbar."

    # Zeilen filtern, die zum Dienst gehören
    rows = [r for r in table.find_all("tr") if len(r.find_all("td")) > 5]
    dienst_rows = [r for r in rows if r.find_all("td")[0].text.strip() == service_id]
    
    if not dienst_rows: return "Keine Dienstdetails gefunden."

    # Start und Ende extrahieren
    start_row = dienst_rows[0]
    end_row = dienst_rows[-1]
    
    # Pausen finden (Spalte 9 ist bei dir der Typ)
    pausen = []
    for r in dienst_rows:
        tds = r.find_all("td")
        if len(tds) > 9 and "Pause" in tds[9].text:
            pausen.append(f"- {tds[1].text} bis {tds[3].text} ({tds[9].text.strip()})")
    
    pausen_str = "\n".join(pausen) if pausen else "Keine Pausen"

    return (f"Beginn: {start_row.find_all('td')[1].text}\n"
            f"Pausen:\n{pausen_str}\n"
            f"Ende: {end_row.find_all('td')[3].text}")
    
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
                # 1. Details abrufen (Datum anpassen, z.B. aus deinem Tag berechnet)
                details = get_service_details(session, "2026-05-29", item['id'])
    
                # 2. Nachricht inkl. Details
                msg = (f"🔔 Neuer Dienst {item['id']}\n"
                       f"📅 Tag: {item['day']}.05.2026\n"
                       f"{details}\n\n"
                       f"👉 Tippe hier, um den Dienst zum Kalender hinzuzufügen!")
    
                # 3. Kalender-Link (hier kannst du 'details' auch in die Parameter aufnehmen)
                headers = {"Click": create_calendar_link(item)} # Hier könntest du noch details als Parameter übergeben
                requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"), headers=headers)
            
            with open(CHECKPOINT_FILE, "w") as f:
                json.dump(current, f, indent=2)
            print("Checkpoint gespeichert.")
        else:
            print("Keine Änderungen.")
            
    except Exception as e:
        print(f"KRITISCHER FEHLER: {e}")

if __name__ == "__main__":
    main()
