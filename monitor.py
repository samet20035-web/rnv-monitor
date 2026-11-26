import os
import sys
import json
import time as time_mod
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta, timezone

BASE_URL = "https://fahrerauskunft.rnv-online.de/WebComm"
LOGIN_URL = f"{BASE_URL}/default.aspx"
ROSTER_URL = f"{BASE_URL}/roster.aspx"
START_URL = f"{LOGIN_URL}?TestingCookie=1"

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
NTFY_TOPIC_MAMA = os.getenv("NTFY_TOPIC_MAMA", "")
USERNAME = os.getenv("RNV_USER", "DEIN_USER")
PASSWORD = os.getenv("RNV_PASS", "DEIN_PASS")
MEIN_NAME = "Samet"

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(BASE_PATH, "checkpoint.json")
ICS_FILE = os.path.join(BASE_PATH, "dienstplan.ics")
STATUS_FILE = os.path.join(BASE_PATH, "status.json")

WOCHENTAG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

ACTIONS_SELF = "view, In Notizen speichern, shortcuts://run-shortcut?name=DienstplanSpeichern"
MAMA_ICON = "https://fahrerauskunft.rnv-online.de/WebComm/images/icons/ios57x57.png"


# ── ICS ───────────────────────────────────────────────────────────────────────
def generate_ics(services, session):
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RNV//Dienstplan//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for s in services:
        jahr = s.get("year", "2026")
        monat = s.get("month", "05")
        tag = s["day"].zfill(2)

        date_str = f"{jahr}-{monat}-{tag}"
        info = get_service_details(session, date_str, s["id"])

        if info["start_time"] and info["start_time"] != "-":
            start_zeit = info["start_time"].replace(":", "") + "00"
            ende_zeit = info["end_time"].replace(":", "") + "00"
            desc = info["text"].replace(chr(10), "\\n")

            ics_lines.append("BEGIN:VEVENT")
            ics_lines.append(f"SUMMARY:Straßenbahn Dienst {s['id']} ({MEIN_NAME})")
            ics_lines.append(f"DTSTART;TZID=Europe/Berlin:{jahr}{monat}{tag}T{start_zeit}")
            ics_lines.append(f"DTEND;TZID=Europe/Berlin:{jahr}{monat}{tag}T{ende_zeit}")
            ics_lines.append(f"DESCRIPTION:{desc}")
            ics_lines.append("END:VEVENT")

    ics_lines.append("END:VCALENDAR")
    return "\n".join(ics_lines)


# ── Login ─────────────────────────────────────────────────────────────────────
def get_current_month_year():
    now = datetime.now(timezone.utc)
    return now.strftime("%m"), now.strftime("%Y")


def get_hidden_fields(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    return {
        inp.get("name"): inp.get("value", "")
        for inp in soup.find_all("input", type="hidden")
        if inp.get("name")
    }


def login(session: requests.Session):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Origin": "https://fahrerauskunft.rnv-online.de",
        "Referer": LOGIN_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    session.get(START_URL, headers=headers, timeout=20)
    r = session.get(LOGIN_URL, headers=headers, timeout=20)
    hidden = get_hidden_fields(r.text)

    payload = {
        **hidden,
        "__EVENTTARGET": "ctl00$cntMainBody$lgnView$lgnLogin$LoginButton",
        "ctl00$cntMainBody$lgnView$lgnLogin$UserName": USERNAME,
        "ctl00$cntMainBody$lgnView$lgnLogin$Password": PASSWORD,
    }

    r2 = session.post(LOGIN_URL, data=payload, headers=headers, timeout=20)
    if r2.status_code == 500:
        raise Exception("Serverfehler 500: RNV blockiert die Anfrage.")
    if not any(x in r2.text.lower() for x in ["logout", "abmelden", "dienstplan"]):
        raise Exception("Login fehlgeschlagen.")


class SiteUnavailable(Exception):
    """RNV-Seite nicht erreichbar bzw. Login nicht möglich."""


def login_with_retry(session, attempts=3):
    for i in range(1, attempts + 1):
        try:
            login(session)
            return
        except Exception as e:
            print(f"Login Versuch {i}/{attempts}: {e}")
            if i == attempts:
                raise SiteUnavailable(str(e))
            time_mod.sleep(10)


# ── Ausfall-Überwachung ───────────────────────────────────────────────────────
# status.json wird nur bei Zustandswechseln geschrieben (Ausfall beginnt,
# Push gesendet, Seite wieder da) -> kein Commit-Spam alle 15 Minuten.
OUTAGE_NOTIFY_AFTER_MIN = 45


def load_status() -> dict:
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_status(status: dict):
    if status:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status, f)
    elif os.path.exists(STATUS_FILE):
        os.remove(STATUS_FILE)


def handle_outage(reason: str):
    now = datetime.now(timezone.utc)
    status = load_status()
    if "down_since" not in status:
        save_status({"down_since": now.isoformat(), "notified": False})
        print("Ausfall erkannt, Beobachtung gestartet.")
        return

    minutes = int((now - datetime.fromisoformat(status["down_since"])).total_seconds() // 60)
    print(f"RNV seit {minutes} Min nicht erreichbar.")
    if not status.get("notified") and minutes >= OUTAGE_NOTIFY_AFTER_MIN:
        msg = (
            f"⚠️ RNV-Dienstplan seit {minutes} Min nicht erreichbar.\n"
            f"Grund: {reason[:150]}\n\n"
            f"Neue Dienste werden erst erkannt, wenn die Seite wieder geht."
        )
        if ntfy(NTFY_TOPIC, "Perdis", msg):
            status["notified"] = True
            save_status(status)


def handle_recovery():
    status = load_status()
    if "down_since" in status:
        if status.get("notified"):
            ntfy(NTFY_TOPIC, "Perdis", "✅ RNV-Dienstplan ist wieder erreichbar.")
        save_status({})


# ── Dienstdetails ─────────────────────────────────────────────────────────────
def get_service_details(session, date_str, service_id):
    session.get(ROSTER_URL, timeout=20)

    payload = {
        "__EVENTTARGET": "ctl00$cntMainBody$calRoster",
        "__EVENTARGUMENT": date_str,
    }
    session.post(ROSTER_URL, data=payload, timeout=20)

    resp = session.get(f"{BASE_URL}/shift.aspx?{date_str}", timeout=20)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": "ctl00_cntMainBody_lstDienstinfo"})

    empty = {"start_time": None, "end_time": None, "start_ort": None, "end_ort": None}

    if not table:
        return {"text": "Details nicht verfügbar.", **empty}

    rows = [r for r in table.find_all("tr") if len(r.find_all("td")) > 5]
    dienst_rows = [r for r in rows if r.find_all("td")[0].text.strip() == service_id]

    if not dienst_rows:
        return {"text": "Keine Dienstdetails gefunden.", **empty}

    def clean_ort(ort: str, typ: str) -> str:
        ort = (ort or "").strip()
        if "Bth. HD Betriebshof" in ort or "Bth HD Betriebshof" in ort:
            return "Betriebshof (Ausrücken)" if typ == "start" else "Betriebshof (Einrücken)"
        return ort

    def fmt_time(t: str) -> str:
        t = (t or "").strip()
        return t if t else "-"

    start_row = dienst_rows[0]
    end_row = dienst_rows[-1]

    tds_start = start_row.find_all("td")
    tds_end = end_row.find_all("td")

    start_time = tds_start[1].text.strip() if len(tds_start) > 1 else "-"
    start_ort_raw = tds_start[2].text.strip() if len(tds_start) > 2 else "-"
    end_time = tds_end[3].text.strip() if len(tds_end) > 3 else "-"
    end_ort_raw = tds_end[4].text.strip() if len(tds_end) > 4 else "-"

    start_ort = clean_ort(start_ort_raw, "start")
    end_ort = clean_ort(end_ort_raw, "end")

    pausen = []
    for r in dienst_rows:
        tds = r.find_all("td")
        if len(tds) > 9:
            art = tds[9].text.strip().lower()
            if "pause" in art:
                pause_von = tds[1].text.strip() if len(tds) > 1 else "-"
                pause_bis = tds[3].text.strip() if len(tds) > 3 else "-"
                pausen.append((pause_von, pause_bis))

    text_parts = [f"Beginn: {fmt_time(start_time)} Uhr ({start_ort})"]

    if pausen:
        for i, (von, bis) in enumerate(pausen, 1):
            text_parts.append(f"{i}. Pause: {von} - {bis} Uhr")
    else:
        text_parts.append("Keine Pausen")

    text_parts.append(f"Ende: {fmt_time(end_time)} Uhr ({end_ort})")

    return {
        "text": "\n".join(text_parts),
        "start_time": start_time,
        "end_time": end_time,
        "start_ort": start_ort,
        "end_ort": end_ort,
    }


# ── Kalender parsen ───────────────────────────────────────────────────────────
def parse_services(html, month, year):
    """Gibt None zurück, wenn der Kalender nicht gefunden wurde (= Abruf fehlgeschlagen)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id=lambda x: x and "calRoster" in x)
    if not table:
        return None

    services = []
    for td in table.find_all("td", {"class": "calDay"}):
        title = td.get("title", "")
        if "Dienst:" in title and "abwesend" not in title:
            day_str = td.find("strong").get_text(strip=True)[:2].strip().zfill(2)
            span = td.find("span")
            time_val = span.get_text(strip=True) if span else ""

            services.append({
                "day": day_str,
                "time": time_val,
                "id": title.split("Dienst:")[1].split("•")[0].strip(),
                "month": month,
                "year": year,
            })
    return services


# ── Vergleich: pro TAG, nicht pro Dienstnummer ────────────────────────────────
def day_key(s) -> str:
    return f"{s['year']}-{str(s['month']).zfill(2)}-{str(s['day']).zfill(2)}"


def group_by_day(items) -> dict:
    result = {}
    for s in items:
        result.setdefault(day_key(s), []).append(s)
    return result


def signature(items):
    return sorted((i["id"], i["time"]) for i in items)


def zeit_only(item) -> str:
    """Im Kalender steht 'Dienstnr  HH:MM - HH:MM' -> nur die Zeit."""
    return item["time"].replace(item["id"], "").strip()


def fmt_items(items) -> str:
    return " + ".join(f"{i['id']} ({zeit_only(i)})" for i in items)


# ── ntfy ──────────────────────────────────────────────────────────────────────
def ntfy(topic, title, msg, extra=None, attempts=3):
    """Sendet an ntfy, prüft den Status und versucht es mehrfach. True = zugestellt."""
    if not topic:
        return True
    headers = {"Title": title}
    if extra:
        headers.update(extra)
    for i in range(1, attempts + 1):
        try:
            r = requests.post(
                f"https://ntfy.sh/{topic}",
                data=msg.encode("utf-8"),
                headers=headers,
                timeout=10,
            )
            if r.status_code == 200:
                print(f"ntfy '{title}': OK")
                return True
            print(f"ntfy '{title}': HTTP {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"ntfy-Fehler ({i}/{attempts}): {e}")
        if i < attempts:
            time_mod.sleep(5 * i)
    return False


# Tage, bei denen der Push NICHT zugestellt wurde -> bleiben im Checkpoint "alt",
# damit der nächste Lauf es erneut versucht
FAILED_DAYS = set()


def push_both(key, msg_self, msg_mama):
    ok = ntfy(NTFY_TOPIC, "Perdis", msg_self, {"Actions": ACTIONS_SELF})
    ntfy(NTFY_TOPIC_MAMA, "Dienstplan Samet RNV", msg_mama, {"Icon": MAMA_ICON})
    if not ok:
        FAILED_DAYS.add(key)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone.utc)
    if not (6 <= now.hour < 17):
        print("Außerhalb der Zeit. Skript pausiert.")
        return

    today = now.date()
    session = requests.Session()

    try:
        # Alten Checkpoint laden
        old = []
        if os.path.exists(CHECKPOINT_FILE):
            try:
                with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                    old = json.load(f)
            except (json.JSONDecodeError, ValueError):
                print("Warnung: Checkpoint-Datei war korrupt, erstelle neue Liste.")
                old = []

        login_with_retry(session)

        # Aktueller Monat (Pflicht)
        month, year = get_current_month_year()
        curr = parse_services(session.get(ROSTER_URL, timeout=20).text, month, year)
        if curr is None:
            raise SiteUnavailable("Kalender (aktueller Monat) nicht gefunden - Abruf fehlgeschlagen.")

        # Nächster Monat (optional: bei Fehler alte Einträge behalten)
        naechster = (now.replace(day=28) + timedelta(days=5)).replace(day=28)
        n_month, n_year = naechster.strftime("%m"), naechster.strftime("%Y")
        nxt = parse_services(
            session.get(f"{ROSTER_URL}?{naechster.strftime('%Y-%m-%d')}", timeout=20).text,
            n_month, n_year,
        )
        if nxt is None:
            print("Warnung: Kalender (nächster Monat) nicht gefunden, übernehme alte Einträge.")
            nxt = [s for s in old if s.get("month") == n_month and s.get("year") == n_year]

        # Seite hat geantwortet -> ggf. Ausfall-Status zurücksetzen
        handle_recovery()

        unique = {f"{s['year']}-{s['month']}-{s['day']}-{s['id']}": s for s in curr + nxt}
        current = list(unique.values())

        old_by_day = group_by_day(old)
        cur_by_day = group_by_day(current)

        # Neu / geändert
        for key in sorted(cur_by_day):
            d = date.fromisoformat(key)
            if d < today:
                continue

            new_items = cur_by_day[key]
            old_items = old_by_day.get(key)
            wt = WOCHENTAG[d.weekday()]
            datum = f"{d.day:02d}.{d.month:02d}.{d.year}"

            if old_items is None:
                print(f"NEU: {key} {fmt_items(new_items)}")
                push_both(
                    key,
                    f"Neuer Dienst\n"
                    f"📅 {wt}, {datum}\n"
                    f"⏰ {fmt_items(new_items)}\n\n",
                    f"📅 Wann: {wt}, {datum}\n"
                    f"⏰ Zeit: {fmt_items(new_items)}\n\n"
                    f"*Samets Dienstplan wurde aktualisiert.*",
                )

            elif signature(old_items) != signature(new_items):
                print(f"GEÄNDERT: {key} {fmt_items(old_items)} -> {fmt_items(new_items)}")
                push_both(
                    key,
                    f"🔔 Dienstplanänderung\n"
                    f"📅 {wt}, {datum}\n"
                    f"⏰ Vorher: {fmt_items(old_items)}\n"
                    f"⏰ Jetzt: {fmt_items(new_items)}\n\n",
                    f"⚠️ Samets Dienst hat sich geändert\n"
                    f"📅 {wt}, {datum}\n"
                    f"⏰ Neue Zeit: {fmt_items(new_items)}\n\n"
                    f"*Der Dienstplan wurde angepasst. Bitte den Kalender prüfen.*",
                )

        # Entfernt
        for key in sorted(old_by_day):
            if key in cur_by_day:
                continue
            d = date.fromisoformat(key)
            if d < today:
                continue

            wt = WOCHENTAG[d.weekday()]
            datum = f"{d.day:02d}.{d.month:02d}.{d.year}"
            print(f"ENTFERNT: {key} {fmt_items(old_by_day[key])}")
            push_both(
                key,
                f"❌ Dienst entfernt\n"
                f"📅 {wt}, {datum}\n"
                f"⏰ Vorher: {fmt_items(old_by_day[key])}\n\n",
                f"⚠️ Samets Dienst am {wt}, {datum} wurde entfernt.\n\n"
                f"*Bitte den Kalender prüfen.*",
            )

        # Checkpoint ZUERST speichern (verhindert Doppel-Pushes).
        # Tage mit fehlgeschlagenem Push behalten den alten Stand -> nächster Lauf sendet erneut.
        to_save = [s for s in current if day_key(s) not in FAILED_DAYS]
        to_save += [s for s in old if day_key(s) in FAILED_DAYS]
        if FAILED_DAYS:
            print(f"Warnung: Push fehlgeschlagen für {sorted(FAILED_DAYS)} - wird beim nächsten Lauf wiederholt.")
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(to_save, f, indent=2, ensure_ascii=False)
        print("Checkpoint gespeichert.")

        # ICS danach; Fehler hier dürfen den Checkpoint nicht verhindern
        try:
            valid_services = [
                s for s in current
                if date(int(s["year"]), int(s["month"]), int(s["day"])) >= today
            ]
            ics_data = generate_ics(valid_services, session)
            with open(ICS_FILE, "w", encoding="utf-8") as f:
                f.write(ics_data)
            print("ICS-Datei aktualisiert.")
        except Exception as e:
            print(f"Warnung: ICS-Erzeugung fehlgeschlagen: {e}")

    except (SiteUnavailable, requests.RequestException) as e:
        # Seite down / blockiert: kein roter Lauf, aber Ausfall wird beobachtet und gemeldet
        print(f"RNV nicht erreichbar: {e}")
        handle_outage(str(e))
    except Exception as e:
        print(f"KRITISCHER FEHLER: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
