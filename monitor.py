import os
import requests
from bs4 import BeautifulSoup
import json
import urllib.parse

# --- KONFIGURATION ---
BASE_URL = "https://fahrerauskunft.rnv-online.de/WebComm"
LOGIN_URL = f"{BASE_URL}/default.aspx"
ROSTER_URL = f"{BASE_URL}/roster.aspx"
START_URL = f"{LOGIN_URL}?TestingCookie=1"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "DEIN_TOPIC")
USERNAME = os.getenv("RNV_USER", "DEIN_USER")
PASSWORD = os.getenv("RNV_PASS", "DEIN_PASS")
# WICHTIG: Absoluten Pfad verwenden
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(BASE_PATH, "checkpoint.json")

def get_hidden_fields(html):
    soup = BeautifulSoup(html, "html.parser")
    return {inp.get("name"): inp.get("value", "") for inp in soup.find_all("input", type="hidden") if inp.get("name")}

def login(session):
    headers = {"User-Agent": "Mozilla/5.0"}
    session.get(START_URL, headers=headers)
    r = session.get(LOGIN_URL, headers=headers)
    hidden = get_hidden_fields(r.text)
    payload = {**hidden, "__EVENTTARGET": "ctl00$cntMainBody$lgnView$lgnLogin$LoginButton",
               "ctl00$cntMainBody$lgnView$lgnLogin$UserName": USERNAME, 
               "ctl00$cntMainBody$lgnView$lgnLogin$Password": PASSWORD}
    r2 = session.post(LOGIN_URL, data=payload, headers=headers)
    if not any(x in r2.text.lower() for x in ["logout", "abmelden", "dienstplan"]):
        raise Exception("Login fehlgeschlagen.")

def get_service_details(session, date_str, service_id):
    # WICHTIG: Die URL benötigt das korrekte Datum Format
    url = f"{BASE_URL}/shift.aspx?date={date_str}" 
    resp = session.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": "ctl00_cntMainBody_lstDienstinfo"})
    if not table: return "Details nicht verfügbar."

    rows = [r for r in table.find_all("tr") if len(r.find_all("td")) > 5]
    dienst_rows = [r for r in rows if r.find_all("td")[0].text.strip() == service_id]
    if not dienst_rows: return "Keine Dienstdetails gefunden."

    start_row = dienst_rows[0]
    end_row = dienst_rows[-1]
    
    start_ort = start_row.find_all("td")[2].text.strip()
    end_ort = end_row.find_all("td")[4].text.strip()
    
    pausen = []
    for r in dienst_rows:
        tds = r.find_all("td")
        if len(tds) > 9 and "Pause" in tds[9].text:
            pausen.append(f"- {tds[1].text} bis {tds[3].text} ({tds[9].text.strip()})")
    
    pausen_str = "\n".join(pausen) if pausen else "Keine Pausen"

    return f"Beginn: {start_row.find_all('td')[1].text} ({start_ort})\n{pausen_str}\nEnde: {end_row.find_all('td')[3].text} ({end_ort})"

def create_calendar_link(service, details):
    try:
        # Fehler abfangen, falls kein Bindestrich da ist
        if "-" in service['time']:
            s, e = service['time'].split("-")
            s_zeit = s.strip().replace(":", "") + "00"
            e_zeit = e.strip().replace(":", "") + "00"
        else:
            s_zeit, e_zeit = "000000", "235900"
        
        date_val = "20260529"
        params = {"action": "TEMPLATE", "text": f"Dienst {service['id']}", 
                  "dates": f"{date_val}T{s_zeit}/{date_val}T{e_zeit}",
                  "details": details, "location": "RNV"}
        return f"https://www.google.com/calendar/render?{urllib.parse.urlencode(params)}"
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
            time_val = span.get_text(strip=True) if span else "00:00-00:00"
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
                    details = get_service_details(session, "2026-05-29", item['id'])
                    msg = f"🔔 Neuer Dienst {item['id']}\n{details}\n👉 Tippe hier zum Kalender!"
                    headers = {"Click": create_calendar_link(item, details)}
                    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"), headers=headers)
            
            with open(CHECKPOINT_FILE, "w") as f:
                json.dump(current, f, indent=2)
    except Exception as e:
        print(f"FEHLER: {e}")

if __name__ == "__main__":
    main()
