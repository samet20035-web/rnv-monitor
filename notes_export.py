import re
from collections import defaultdict

# -----------------------------
# STOP-KÜRZEL MAP
# -----------------------------

STOP_MAP = {
    "Heiligenbergschule": "HHHS",
    "Bismarckplatz": "BHBP",
    "Hans-Thoma-Platz": "HHTP",
    "Betriebshof": "BHBH",
    "Bth. HD Betriebshof": "BHBE",
    "HD Betriebshof": "BHBE",
    "Kirchheim Friedhof": "KHFH",
    "Rohrbach Süd": "RSRS",
    "Eppelheim Kirchheimer Straße": "EHKS",
}

SKIP_LINES = [
    "keine Fahrt",
    "---",
]

# -----------------------------
# NORMALISIERUNG
# -----------------------------

def norm_stop(text: str) -> str:
    text = text.strip()
    return STOP_MAP.get(text, text)


def is_skip(line: str) -> bool:
    l = line.lower()
    return any(s in l for s in SKIP_LINES)


# -----------------------------
# HEADER PARSER
# -----------------------------

def parse_header(line: str):
    m = re.match(r"^(Mo|Di|Mi|Do|Fr|Sa|So),\s*([\d.]+)\s+(\d+)", line)
    if not m:
        return None
    return {
        "date": f"{m.group(1)}, {m.group(2)}",
        "dienst": m.group(3)
    }


# -----------------------------
# FAHRT PARSER
# -----------------------------

def parse_trip(line: str):
    """
    Format:
    BHBH  07:41  26 KHFH
    """
    m = re.match(r"^(\S+)\s+(\d{1,2}:\d{2})\s+(\d+)\s+(.+)$", line)
    if not m:
        return None

    return {
        "from": norm_stop(m.group(1)),
        "time": m.group(2),
        "line": m.group(3),
        "to": norm_stop(m.group(4)),
    }


# -----------------------------
# UMLAUF
# -----------------------------

def parse_umlauf(line: str):
    m = re.match(r"^\s*=>\s*(\d+)", line)
    return m.group(1) if m else None


# -----------------------------
# MAIN PARSER
# -----------------------------

def process(lines):
    header = None
    output = []

    current_trip = None
    last_umlauf = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # HEADER
        h = parse_header(line)
        if h:
            header = h
            output.append(f"{h['date']}   {h['dienst']}\n")
            continue

        if is_skip(line):
            continue

        # UMLAUF
        uml = parse_umlauf(line)
        if uml and current_trip:
            current_trip["umlauf"] = uml
            continue

        # TRIP
        trip = parse_trip(line)
        if trip:
            if current_trip:
                output.append(format_trip(current_trip, last_umlauf))
                if current_trip.get("umlauf"):
                    last_umlauf = current_trip["umlauf"]

            current_trip = trip
            continue

    if current_trip:
        output.append(format_trip(current_trip, last_umlauf))

    return "\n".join(output)


# -----------------------------
# FORMAT OUTPUT
# -----------------------------

def format_trip(t, last_umlauf):
    out = []

    out.append(f"{t['from']}  {t['time']}  {t['line']} {t['to']}")

    uml = t.get("umlauf")
    if uml and uml != last_umlauf:
        out.append(f"       => {uml}")

    out.append("")
    return "\n".join(out)


# -----------------------------
# FILE IO (GITHUB ACTION)
# -----------------------------

if __name__ == "__main__":
    input_file = "input.txt"
    output_file = "output.txt"

    with open(input_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    result = process(lines)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(result)

    print("Fertig:", output_file)
