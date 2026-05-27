import os
import requests
from bs4 import BeautifulSoup
import json
import urllib.parse
from datetime import datetime

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
    if not table: return "Details nicht verfügbar."

    rows = table.find_all("tr")
    relevant = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) > 5 and cols[0].text.strip() == service_id:
            relevant.append({
                "von": cols[1].text.strip(), "start": cols[2].text.strip(),
                "bis": cols[3].text.strip(), "end": cols[4].text.strip(),
                "typ": cols[9].text.strip()
            })
    if not relevant: return "Keine Details gefunden."
    
    pausen = [r for r in relevant if "Pause" in r["typ"]]
    p_str = f"{pausen[0]['von']} - {pausen[0]['bis']}" if pausen else "Keine"
    return f"Beginn: {relevant[0]['von']} ({relevant[0]['start']})\nPause: {p_str}\nEnde: {relevant[-1]['bis']} ({relevant[-1]['end']})"

def create_calendar_link(service, details_text):
    s, e = service['time'].split("-")
    s_zeit = s.strip().replace(":", "") + "00"
    e_zeit = e.strip().replace(":", "") + "00"
    datum = "20260529T" 
    
    params = {
        "text": f"Straßenbahn Dienst {service['id']} (Samet)",
        "dates": f"{datum}{s_zeit}/{datum}{e_zeit}",
        "details": details_text,
        "location": "RNV Betriebshof"
    }
    return f"https://www.google.com/calendar/render?action=TEMPLATE&{urllib.parse.urlencode(params)}"

def parse_services(html: str):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"id": "ctl00_ctl00_cntMainBody_calRoster"})
    services = []
    if not table: return services
    for td in table.find_all("td", {"class": "calDay"}):
        title = td.get("title", "")
        if "Dienst:" in title and "abwesend" not in title:
            day = td.find("strong").get_text(strip=True)[:2]
            span = td.find("span")
            time_val = span.get_text(strip=True) if span else ""
            dienst_id = title.split("Dienst:")[1].split("•")[0].strip()
            if dienst_id in time_val: time_val = time_val.replace(dienst_id, "").strip()
            services.append({"day": day, "time": time_val, "id": dienst_id})
    return services

def notify(session, service):
    details = get_service_details(session, "2026-05-29", service['id'])
    link = create_calendar_link(service, details)
    msg = f"🔔 Dienst {service['id']}\n📅 {service['day']}.05.2026\n{details}"
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"),
                  headers={"Title": "Neuer Dienst", "Priority": "high", "Click": link})

def main():
    session = requests.Session()
    try:
        login(session)
        current = parse_services(session.get(BASE_URL).text)
        old = json.load(open("checkpoint.json")) if os.path.exists("checkpoint.json") else []
        if current != old:
            for item in current:
                if item not in old:
                    notify(session, item)
            json.dump(current, open("checkpoint.json", "w"), indent=2)
    except Exception as e:
        print(f"Fehler: {e}")

if __name__ == "__main__":
    main()
