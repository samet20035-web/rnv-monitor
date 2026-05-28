from collections import defaultdict
from datetime import datetime

# =========================
# 1. STOP ALIASES
# =========================
STOP_MAP = {
    "Heiligenbergschule": "HHHS",
    "Bismarplatz": "BHBP",
}

# =========================
# 2. OPTIONALE LINIENREGELN
# (hier später erweiterbar)
# =========================
LINE_RULES = {
    # Beispielstruktur für später
    22: {},
    23: {},
    24: {},
    26: {},
}

# =========================
# 3. FORMAT HELPERS
# =========================
def norm_stop(name: str) -> str:
    return STOP_MAP.get(name, name)


def format_header(date_str, dienst):
    return f"{date_str}   {dienst}"


def format_line(stop, time, line, end):
    return f"{stop}  {time}  {line} {end}"


def format_umlauf(umlauf):
    return f"       => {umlauf}"


# =========================
# 4. CORE LOGIC
# =========================
def build_output(entries, date_str, dienst):
    """
    entries = Liste von Fahrten in chronologischer Reihenfolge
    """

    output = []
    output.append(format_header(date_str, dienst))
    output.append("")

    last_umlauf = None

    for e in entries:

        stop = norm_stop(e["stop"])
        time = e["time"]
        line = e["line"]
        end = e["end"]
        umlauf = e.get("umlauf")

        # Hauptzeile
        output.append(format_line(stop, time, line, end))

        # Umlauf nur bei Wechsel anzeigen
        if umlauf and umlauf != last_umlauf:
            output.append(format_umlauf(umlauf))
            last_umlauf = umlauf

        output.append("")  # Blocktrennung

    return "\n".join(output).strip() + "\n"


# =========================
# 5. GROUPING (falls mehrere Tage im Feed)
# =========================
def group_by_day(data):
    grouped = defaultdict(list)

    for e in data:
        grouped[(e["date"], e["dienst"])].append(e)

    return grouped


# =========================
# 6. MAIN EXPORT
# =========================
def export_all(data):
    grouped = group_by_day(data)

    for (date_str, dienst), entries in grouped.items():

        # Zeit sortieren
        entries.sort(key=lambda x: x["time"])

        content = build_output(entries, date_str, dienst)

        filename = f"notes/{date_str.replace('.', '-')}_{dienst}.txt"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"Geschrieben: {filename}")


# =========================
# 7. EXAMPLE ENTRY FORMAT
# =========================
if __name__ == "__main__":

    sample_data = [
        {
            "date": "Fr, 29.05.26",
            "dienst": "2061033",
            "stop": "BHBH",
            "time": "07:41",
            "line": "26",
            "end": "KHFH",
            "umlauf": "2657"
        },
        {
            "date": "Fr, 29.05.26",
            "dienst": "2061033",
            "stop": "BHBP",
            "time": "11:55",
            "line": "26",
            "end": "KHFH",
            "umlauf": "2657"
        },
        {
            "date": "Fr, 29.05.26",
            "dienst": "2061033",
            "stop": "BHBH",
            "time": "13:21",
            "line": "26",
            "end": "KHFH",
            "umlauf": "2663"
        },
        {
            "date": "Fr, 29.05.26",
            "dienst": "2061033",
            "stop": "BHBH",
            "time": "16:33",
            "line": "24",
            "end": "RSRS",
            "umlauf": "2663"
        },
    ]

    export_all(sample_data)
