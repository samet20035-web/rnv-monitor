import os
import requests
from bs4 import BeautifulSoup
import hashlib
import json

BASE_URL = "https://DEINE-RNV-SEITE/roster.aspx"
LOGIN_URL = "https://DEINE-RNV-SEITE/default.aspx"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "rnv-dienstplan")
ICON_URL = "https://fahrerauskunft.rnv-online.de/WebComm/images/icons/ios80x80.png"

USERNAME = os.getenv("RNV_USER")
PASSWORD = os.getenv("RNV_PASS")


# -----------------------------
# UTIL: Hash für Change Detection
# -----------------------------
def make_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -----------------------------
# LOGIN (ASP.NET robust)
# -----------------------------
def login(session: requests.Session):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
        "Origin": "https://DEINE-RNV-SEITE",
        "Referer": LOGIN_URL,
    }

    # 1. GET Loginseite (VIEWSTATE holen)
    r = session.get(LOGIN_URL, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    def get_value(name):
        tag = soup.find("input", {"name": name})
        return tag["value"] if tag else ""

    payload = {
        "__VIEWSTATE": get_value("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": get_value("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": get_value("__EVENTVALIDATION"),
        "ctl00$txtUsername": USERNAME,
        "ctl00$txtPassword": PASSWORD,
        "ctl00$btnLogin": "Login",
    }

    r2 = session.post(LOGIN_URL, data=payload, headers=headers)

    if "logout" not in r2.text.lower() and "abmelden" not in r2.text.lower():
        raise Exception("Login fehlgeschlagen – bitte Credentials prüfen")

    return session


# -----------------------------
# HTML PARSER (Dienstplan)
# -----------------------------
def parse_services(html: str):
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", {"id": "ctl00_ctl00_cntMainBody_calRoster"})
    if not table:
        raise Exception("Dienstplan-Tabelle nicht gefunden (evtl. nicht eingeloggt)")

    services = []

    for td in table.find_all("td"):
        title = td.get("title", "")
        if "Dienst:" not in title:
            continue

        strong = td.find("strong")
        span = td.find("span")

        day = strong.get_text(strip=True) if strong else ""
        time = span.get_text(strip=True) if span else ""

        # Dienstnummer extrahieren
        dienst_id = ""
        if "Dienst:" in title:
            try:
                dienst_id = title.split("Dienst:")[1].split("•")[0].strip()
            except:
                pass

        services.append({
            "day": day,
            "time": time,
            "id": dienst_id,
            "raw": title
        })

    return services


# -----------------------------
# DIFF LOGIK
# -----------------------------
def diff(old, new):
    old_map = {x["id"] + x["day"]: x for x in old}
    new_map = {x["id"] + x["day"]: x for x in new}

    changes = []

    # neue + geänderte
    for k, v in new_map.items():
        if k not in old_map:
            changes.append(("NEW", v))
        elif old_map[k]["time"] != v["time"]:
            changes.append(("CHANGED", old_map[k], v))

    # entfernte
    for k, v in old_map.items():
        if k not in new_map:
            changes.append(("REMOVED", v))

    return changes


# -----------------------------
# FORMAT PUSH MESSAGE
# -----------------------------
def format_message(change):
    if change[0] == "NEW":
        d = change[1]
        return f"Neuer Dienst am {d['day']}\n{d['time']}\nDienst: {d['id']}"

    if change[0] == "CHANGED":
        old, new = change[1], change[2]
        return (
            f"Dienst geändert am {new['day']}\n"
            f"Alt: {old['time']}\n"
            f"Neu: {new['time']}\n"
            f"Dienst: {new['id']}"
        )

    if change[0] == "REMOVED":
        d = change[1]
        return f"Dienst entfernt am {d['day']}\n{d['time']}\nDienst: {d['id']}"


# -----------------------------
# PUSH NOTIFICATION
# -----------------------------
def notify(message):
    url = f"https://ntfy.sh/{NTFY_TOPIC}"

    headers = {
        "Title": "Perdis",
        "Icon": ICON_URL,
        "Priority": "high",
        "Tags": "train,calendar"
    }

    # WICHTIG: verhindert “statische Wiederverwendung”
    params = {
        "t": str(__import__("time").time())  # Cache-Buster
    }

    requests.post(
        url,
        data=message.encode("utf-8"),
        headers=headers,
        params=params
    )


# -----------------------------
# MAIN
# -----------------------------
def main():
    session = requests.Session()

    try:
        login(session)

        r = session.get(BASE_URL)

        html = r.text

        # DEBUG falls wieder Fehler
        if "Dienstplan" not in html and "calRoster" not in html:
            with open("debug.html", "w", encoding="utf-8") as f:
                f.write(html)
            raise Exception("Keine gültige Dienstplan-Seite geladen")

        current = parse_services(html)

    except Exception as e:
        print("ERROR:", str(e))
        return

    # checkpoint aus GitHub Actions / Pipedream
    old = []
    if os.path.exists("checkpoint.json"):
        with open("checkpoint.json", "r") as f:
            old = json.load(f)

    changes = diff(old, current)

    if changes:
        for c in changes:
            msg = format_message(c)
            print(msg)
            notify(msg)

    # speichern
    with open("checkpoint.json", "w") as f:
        json.dump(current, f, indent=2)


if __name__ == "__main__":
    main()
