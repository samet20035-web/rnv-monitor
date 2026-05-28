import re
from collections import defaultdict

# -----------------------------
# KONFIG
# -----------------------------

SKIP_KEYWORDS = [
    "Betriebshof",
    "BH HD",
    "BHD",
    "BTH",
]

STOP_MAP = {
    "Bth. HD Betriebshof": "BHBE",
    "Bth HD Betriebshof": "BHBE",
    "Betriebshof": "BHBH",
    "Bismarckplatz": "BHBP",
    "Hauptbahnhof": "BHHF",
    "Rohrbach Süd": "RSRS",
    "Kirchheim Friedhof": "KHFH",
    "Leimen Friedhof": "LHFH",
    "Kirchheimer Straße": "EHKS",
    "Hans-Thoma-Platz": "HHHT",
    "Heiligenbergschule": "HHHS",
}


DAYS_MAP = {
    "Mo": "Mo",
    "Di": "Di",
    "Mi": "Mi",
    "Do": "Do",
    "Fr": "Fr",
    "Sa": "Sa",
    "So": "So",
}


# -----------------------------
# HILFSFUNKTIONEN
# -----------------------------

def clean_stop(code: str) -> str:
    return STOP_MAP.get(code.strip(), code.strip())


def is_skip(line: str) -> bool:
    return any(k.lower() in line.lower() for k in SKIP_KEYWORDS)


def parse_header(line: str):
    """
    Fr, 29.05.26   2061033
    """
    m = re.match(r"^(Mo|Di|Mi|Do|Fr|Sa|So),\s*([\d.]+)\s+(\d+)", line)
    if not m:
        return None
    return f"{m.group(1)}, {m.group(2)}   {m.group(3)}"


def parse_trip(line: str):
    """
    BHBH  07:41  26 KHFH
    """
    m = re.match(r"^(\w+)\s+(\d{1,2}:\d{2})\s+(\d+)\s+(\w+)", line)
    if not m:
        return None

    return {
        "from": clean_stop(m.group(1)),
        "time": m.group(2),
        "line": m.group(3),
        "to": clean_stop(m.group(4)),
        "raw_from": m.group(1),
        "raw_to": m.group(4),
    }


def parse_umlauf(line: str):
    """
    => 2657
    """
    m = re.match(r"^\s*=>\s*(\d+)", line)
    if not m:
        return None
    return m.group(1)


# -----------------------------
# HAUPTPARSER
# -----------------------------

def process_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    output_blocks = []
    current_header = None
    current_block = []

    pending_trip = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Header
        header = parse_header(line)
        if header:
            if current_block:
                output_blocks.append((current_header, current_block))
                current_block = []

            current_header = header
            continue

        # Skip Betriebshof / useless lines
        if is_skip(line):
            continue

        # Umlaufnummer
        umlauf = parse_umlauf(line)
        if umlauf and pending_trip:
            pending_trip["umlauf"] = umlauf
            current_block.append(pending_trip)
            pending_trip = None
            continue

        # Trip line
        trip = parse_trip(line)
        if trip:
            pending_trip = trip
            continue

    if current_block:
        output_blocks.append((current_header, current_block))

    return output_blocks


# -----------------------------
# FORMAT OUTPUT
# -----------------------------

def format_blocks(blocks):
    out = []

    for header, trips in blocks:
        if not header:
            continue

        out.append(header)
        out.append("")

        for t in trips:
            out.append(f"{t['from']}  {t['time']}  {t['line']} {t['to']}")
            if "umlauf" in t:
                out.append(f"       => {t['umlauf']}")
            out.append("")

    return "\n".join(out)


# -----------------------------
# MAIN (GITHUB ACTION)
# -----------------------------

if __name__ == "__main__":
    input_file = "input.txt"   # <- deine Rohdaten
    output_file = "output.txt"

    blocks = process_file(input_file)
    result = format_blocks(blocks)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(result)

    print("Fertig geschrieben:", output_file)
