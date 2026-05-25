import os
import re
import json
import hashlib
import requests
from bs4 import BeautifulSoup

# =========================================================
# CONFIG
# =========================================================

LOGIN_URL = os.getenv("RNV_LOGIN_URL")
ROSTER_URL = os.getenv("RNV_ROSTER_URL")

USERNAME = os.getenv("RNV_USER")
PASSWORD = os.getenv("RNV_PASS")

NTFY_TOPIC = os.getenv("NTFY_TOPIC")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

STATE_FILE = "state/roster.json"

session = requests.Session()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36"
}

# =========================================================
# HELPERS
# =========================================================

def send_ntfy(msg: str):
    requests.post(
        NTFY_URL,
        data=msg.encode("utf-8"),
        headers={"Title": "RNV Dienstplan"},
        timeout=20
    )


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(data):
    os.makedirs("state", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================================================
# LOGIN
# =========================================================

def login():
    page = session.get(LOGIN_URL, headers=HEADERS)
    soup = BeautifulSoup(page.text, "html.parser")

    def get_hidden(name):
        tag = soup.find("input", {"name": name})
        return tag["value"] if tag else ""

    payload = {
        "__VIEWSTATE": get_hidden("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": get_hidden("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": get_hidden("__EVENTVALIDATION"),

        "txtUsername": USERNAME,
        "txtPassword": PASSWORD,
        "btnLogin": "Login"
    }

    r = session.post(LOGIN_URL, data=payload, headers=HEADERS)
    return r.text


# =========================================================
# PARSER (DIE WICHTIGE LOGIK)
# =========================================================

def parse_services(html):
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", {"id": "ctl00_ctl00_cntMainBody_calRoster"})
    if not table:
        raise Exception("Dienstplan-Tabelle nicht gefunden")

    services = {}

    for cell in table.find_all("td"):
        href = cell.get("href") or ""
        match_date = re.search(r"(\d{4}-\d{2}-\d{2})", href)

        tooltip = cell.get("title", "")

        if not match_date:
            continue

        date = match_date.group(1)

        # ERSA / frei
        if "ERSA" in cell.text or "abwesend" in tooltip.lower():
            continue

        # Dienst erkennen
        dienst_match = re.search(r"(\d{6,})", tooltip)
        time_match = re.search(r"(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})", tooltip)

        if time_match:
            services[date] = {
                "dienst": dienst_match.group(1) if dienst_match else "UNKNOWN",
                "start": time_match.group(1),
                "end": time_match.group(2)
            }

    return services


# =========================================================
# DIFF LOGIK
# =========================================================

def compare(old, new):
    old_keys = set(old.keys())
    new_keys = set(new.keys())

    added = new_keys - old_keys
    removed = old_keys - new_keys
    common = old_keys & new_keys

    changes = []

    # NEU
    for d in added:
        s = new[d]
        changes.append(
            f"Neuer Dienst am {d}\n{s['start']} - {s['end']}\nDienst: {s['dienst']}"
        )

    # GELÖSCHT
    for d in removed:
        s = old[d]
        changes.append(
            f"Dienst entfernt am {d}\n{s['start']} - {s['end']}"
        )

    # GEÄNDERT
    for d in common:
        if old[d] != new[d]:
            changes.append(
                f"Dienst geändert am {d}\n"
                f"Alt: {old[d]['start']} - {old[d]['end']}\n"
                f"Neu: {new[d]['start']} - {new[d]['end']}"
            )

    return changes


# =========================================================
# MAIN
# =========================================================

def main():

    login()

    html = session.get(ROSTER_URL, headers=HEADERS).text

    new_state = parse_services(html)
    old_state = load_state()

    changes = compare(old_state, new_state)

    if changes:
        for msg in changes:
            send_ntfy(msg)
            print("SENT:", msg)
    else:
        print("Keine Änderungen")

    save_state(new_state)


if __name__ == "__main__":
    main()
