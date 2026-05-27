import os
import requests
from bs4 import BeautifulSoup
import json
import urllib.parse

def login(session: requests.Session):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": LOGIN_URL,
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
    
    if not table: return "Details nicht geladen."

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
    
    if not relevant: return "Keine Details für diese ID."

    pausen = [r for r in relevant if "Pause" in r["typ"]]
    p_str = f"{pausen[0]['von']} - {pausen[0]['bis']}" if pausen else "Keine"
    return f"Beginn: {relevant[0]['von']} ({relevant[0]['start']})\nPause: {p_str}\nEnde: {relevant[-1]['bis']} ({relevant[-1]['end']})"

def create_calendar_link(service):
    s, e = service['time'].split("-")
    s_zeit = s.strip().replace(":", "") + "00"
    e_zeit = e.strip().replace(":", "") + "00"
    datum = "20260529T" 
    
    params = {
        "text": f"Straßenbahn Dienst {service['id']} (Samet)",
        "dates": f"{datum}{s_zeit}/{datum}{e_zeit}",
        "details": f"Dienstnummer: {service['id']}",
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
    link = create_calendar_link(service)
    msg = f"🔔 Neuer Dienst {service['id']}\n📅 {service['day']}.05.2026\n⏰ {service['time']}\n\n{details}"
    
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}", 
        data=msg.encode("utf-8"),
        headers={"Title": "Dienstplan Update", "Priority": "high", "Click": link}
    )

def main():
    session = requests.Session()
    try:
        print("Starte Login...")
        login(session)
        print("Login OK. Lade Dienstplan...")
        
        response = session.get(BASE_URL)
        html = response.text
        
        # DEBUG: Wir speichern den rohen HTML Inhalt, um zu sehen, ob wir auf der richtigen Seite sind
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("HTML wurde in debug_page.html gespeichert. Prüfe diese Datei!")

        current = parse_services(html)
        print(f"Gefundene Dienste: {len(current)}")

        # Datei erzwingen, selbst wenn sie leer ist, um zu sehen, ob das Schreiben klappt
        with open("checkpoint.json", "w") as f:
            json.dump(current, f, indent=2)
        print("checkpoint.json wurde geschrieben.")
            
    except Exception as e:
        print(f"FEHLER im Ablauf: {e}")
