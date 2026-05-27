import os
import requests
from bs4 import BeautifulSoup
import json
import urllib.parse

# --- KONFIGURATION ---
BASE_URL = "https://fahrerauskunft.rnv-online.de/WebComm/roster.aspx"
LOGIN_URL = "https://fahrerauskunft.rnv-online.de/WebComm/default.aspx"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "DEIN_TOPIC")
USERNAME = os.getenv("RNV_USER", "DEIN_USER")
PASSWORD = os.getenv("RNV_PASS", "DEIN_PASS")

# Pfad zur Datei immer im selben Ordner wie das Skript
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(BASE_PATH, "checkpoint.json")

def login(session: requests.Session):
    headers = {"User-Agent": "Mozilla/5.0", "Referer": LOGIN_URL, "Content-Type": "application/x-www-form-urlencoded"}
    r = session.get(LOGIN_URL, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")
    
    def get_input(name):
        tag = soup.find("input", {"name": name})
        return tag["value"] if tag and tag.has_attr("value") else ""

    payload = {
        "__VIEWSTATE": get_input("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": get_input("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": get_input("__EVENTVALIDATION"),
        "ctl00$cntMainBody$lgnView$lgnLogin$UserName": USERNAME,
        "ctl00$cntMainBody$lgnView$lgnLogin$Password": PASSWORD,
        "ctl00$cntMainBody$lgnView$lgnLogin$LoginButton": "Anmelden"
    }
    r2 = session.post(LOGIN_URL, data=payload, headers=headers)
    if not ("logout" in r2.text.lower() or "abmelden" in r2.text.lower() or "Dienstplan" in r2.text):
        raise Exception("Login fehlgeschlagen.")

def get_service_details(session, date_str, service_id):
    url = f"https://fahrerauskunft.rnv-online.de/WebComm/shift.aspx?{date_str}"
    resp = session.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": "ctl00_cntMainBody_lstDienstinfo"})
    if not table: return "Details nicht geladen."
    
    rows = table.find_all("tr")
    relevant = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) > 5 and cols[0].text.strip() == service_id:
            relevant.append({"von": cols[1].text.strip(), "start": cols[2].text.strip(), "bis": cols[3].text.strip(), "end": cols[4].text.strip(), "typ": cols[9].text.strip()})
    
    if not relevant: return "Keine Details gefunden."
    pausen = [r for r in relevant if "Pause" in r["typ"]]
    p_str = f"{pausen[0]['von']} - {pausen[0]['bis']}" if pausen else "Keine"
    return f"Beginn: {relevant[0]['von']} ({relevant[0]['start']})\nPause: {p_str}\nEnde: {relevant[-1]['bis']} ({relevant[-1]['end']})"

def create_calendar_link(service):
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

def parse_services(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "ctl00_ctl00_cntMainBody_calRoster"})
    if not table: return []
    services = []
    for td in table.find_all("td", {"class": "calDay"}):
        title = td.get("title", "")
        if "Dienst:" in title and "abwesend" not in title:
            day = td.find("strong").get_text(strip=True)[:2]
            span = td.find("span")
            time_val = span.get_text(strip=True).replace(title.split("Dienst:")[1].split("•")[0].strip(), "").strip() if span else ""
            services.append({"day": day, "time": time_val, "id": title.split("Dienst:")[1].split("•")[0].strip()})
    return services

def main():
    session = requests.Session()
    try:
        login(session)
        html = session.get(BASE_URL).text
        current = parse_services(html)
        
        # Debugging falls keine Dienste gefunden werden
        if not current:
            with open(os.path.join(BASE_PATH, "debug_page.html"), "w", encoding="utf-8") as f:
                f.write(html)
            print("Keine Dienste gefunden! debug_page.html wurde erstellt.")
        
        old = json.load(open(CHECKPOINT_FILE)) if os.path.exists(CHECKPOINT_FILE) else []
        
        if current != old:
            for item in current:
                if item not in old:
                    details = get_service_details(session, "2026-05-29", item['id'])
                    msg = f"🔔 Neuer Dienst {item['id']}\n📅 {item['day']}.05.2026\n⏰ {item['time']}\n\n{details}"
                    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"), headers={"Click": create_calendar_link(item)})
            
            with open(CHECKPOINT_FILE, "w") as f:
                json.dump(current, f, indent=2)
            print("Änderungen verarbeitet und gespeichert.")
        else:
            print("Keine Änderungen.")
    except Exception as e:
        print(f"Fehler aufgetreten: {e}")

if __name__ == "__main__":
    main()
