import os
import requests
from bs4 import BeautifulSoup
import json
import urllib.parse
from datetime import datetime

# --- KONFIGURATION ---
BASE_URL = "https://fahrerauskunft.rnv-online.de/WebComm"
ROSTER_URL = f"{BASE_URL}/roster.aspx"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "DEIN_TOPIC")
CHECKPOINT_FILE = "checkpoint.json"

def get_service_details(session, date_str, service_id):
    """Ruft die Detailseite auf und extrahiert Start/Ende und Pausen."""
    url = f"{BASE_URL}/shift.aspx?{date_str}"
    resp = session.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": "ctl00_cntMainBody_lstDienstinfo"})
    if not table: return "Details nicht verfügbar."

    rows = [r for r in table.find_all("tr") if len(r.find_all("td")) > 5]
    
    # Filtere nur die Zeilen, die zum Dienst gehören
    dienst_rows = [r for r in rows if r.find_all("td")[0].text.strip() == service_id]
    if not dienst_rows: return "Keine Dienstdetails gefunden."

    start_row = dienst_rows[0]
    end_row = dienst_rows[-1]
    
    # Orte bereinigen
    start_ort = start_row.find_all("td")[2].text.strip().replace("Bth. HD Bergheim", "Betriebshof (Ausrücken)")
    end_ort = end_row.find_all("td")[4].text.strip().replace("Bth. HD Bergheim", "Betriebshof (Einrücken)")
    
    pausen = [r for r in dienst_rows if "Pause" in r.find_all("td")[9].text]
    pausen_str = "\n".join([f"- {p.find_all('td')[1].text} bis {p.find_all('td')[3].text}" for p in pausen]) or "Keine Pausen"

    return (f"Beginn: {start_row.find_all('td')[1].text} Uhr ({start_ort})\n"
            f"Pausen:\n{pausen_str}\n"
            f"Ende: {end_row.find_all('td')[3].text} Uhr ({end_ort})")

def create_calendar_link(service, details):
    """Erzeugt den Google Kalender Link mit dem exakten Schema."""
    title = f"Straßenbahn Dienst {service['id']} (Samet)"
    s, e = service['time'].split("-")
    
    # Datum fest auf 2026-05-29 (laut Beispiel)
    date_val = "20260529"
    s_zeit = s.strip().replace(":", "") + "00"
    e_zeit = e.strip().replace(":", "") + "00"
    
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{date_val}T{s_zeit}/{date_val}T{e_zeit}",
        "details": details,
        "location": "RNV"
    }
    return f"https://www.google.com/calendar/render?{urllib.parse.urlencode(params)}"

def main():
    # ... [Login-Logik hier wie gehabt] ...
    # Wenn ein neuer Dienst erkannt wurde:
    
    details = get_service_details(session, "2026-05-29", item['id'])
    cal_link = create_calendar_link(item, details)
    
    msg = (
        f"📅 Tag: {item['day']}.05.2026\n"
        f"⏰ Zeit: {item['time']}\n"
        f"🆔 Dienstnummer: {item['id']}\n\n"
        f"👉 Tippe auf die Nachricht, um den Dienst zum Kalender hinzuzufügen!"
    )
    
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", 
                  data=msg.encode("utf-8"), 
                  headers={"Click": cal_link})

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
                    msg = (
                        f"🔔 Neuer Dienst {item['id']}\n"
                        f"📅 Tag: {item['day']}.05.2026\n"
                        f"⏰ Zeit: {item['time']}\n"
                        f"🆔 Dienstnummer: {item['id']}\n\n"
                        f"👉 Tippe auf die Nachricht, um den Dienst zum Kalender hinzuzufügen!"
                    )
                    # Kalender-Link als Click-Attribut in der ntfy-Nachricht
                    headers = {"Click": create_calendar_link(item)}
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
