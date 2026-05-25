from __future__ import annotations

import hashlib
import html as html_lib
import os
import re
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

import requests


LOGIN_URL = os.getenv("RNV_LOGIN_URL", "https://example.com/default.aspx")
ROSTER_URL = os.getenv("RNV_ROSTER_URL", "https://example.com/roster.aspx")
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

USERNAME = os.environ["RNV_USER"]
PASSWORD = os.environ["RNV_PASS"]

STATE_FILE = Path(os.getenv("STATE_FILE", "state/last_hash.txt"))


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def origin_from_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


ORIGIN = origin_from_url(LOGIN_URL)


def parse_attrs(tag_fragment: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for key, value in re.findall(r'([A-Za-z_:][\w:.$-]*)\s*=\s*"([^"]*)"', tag_fragment):
        attrs[key.lower()] = html_lib.unescape(value)
    for key, value in re.findall(r"([A-Za-z_:][\w:.$-]*)\s*=\s*'([^']*)'", tag_fragment):
        attrs.setdefault(key.lower(), html_lib.unescape(value))
    return attrs


def extract_hidden_fields(html_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for m in re.finditer(r"<input\b([^>]*)>", html_text, re.IGNORECASE | re.DOTALL):
        attrs = parse_attrs(m.group(1))
        if attrs.get("type", "").lower() == "hidden" and attrs.get("name"):
            fields[attrs["name"]] = attrs.get("value", "")
    return fields


def infer_login_fields(html_text: str) -> tuple[str, str, str | None, str]:
    user_field = os.getenv("RNV_USER_FIELD", "").strip() or None
    pass_field = os.getenv("RNV_PASS_FIELD", "").strip() or None
    submit_field = os.getenv("RNV_SUBMIT_FIELD", "").strip() or None
    submit_value = os.getenv("RNV_SUBMIT_VALUE", "Login").strip()

    inputs = []
    for m in re.finditer(r"<input\b([^>]*)>", html_text, re.IGNORECASE | re.DOTALL):
        attrs = parse_attrs(m.group(1))
        if attrs:
            inputs.append(attrs)

    if not user_field:
        text_inputs = [
            i for i in inputs
            if i.get("type", "text").lower() in {"text", "email", "tel", "search"}
        ]
        scored = sorted(
            text_inputs,
            key=lambda i: (
                0 if re.search(
                    r"(user|login|name|benutzer|id)",
                    f"{i.get('name', '')} {i.get('id', '')}",
                    re.I,
                ) else 1,
                len(i.get("name", "")) or 999,
            ),
        )
        if scored:
            user_field = scored[0].get("name")

    if not pass_field:
        pwd = next(
            (i for i in inputs if i.get("type", "").lower() == "password" and i.get("name")),
            None,
        )
        if pwd:
            pass_field = pwd.get("name")

    if not submit_field:
        submit = next(
            (i for i in inputs if i.get("type", "").lower() in {"submit", "button"} and i.get("name")),
            None,
        )
        if submit:
            submit_field = submit.get("name")
            submit_value = submit.get("value", submit_value)

    if not user_field or not pass_field:
        raise RuntimeError(
            "Login-Feldnamen konnten nicht automatisch erkannt werden. "
            "Setze RNV_USER_FIELD und RNV_PASS_FIELD als GitHub Secrets."
        )

    return user_field, pass_field, submit_field, submit_value


def extract_relevant_content(html_text: str) -> str:
    patterns = [
        r'(<table\b[^>]*id=["\']ctl00_ctl00_cntMainBody_calRoster["\'][^>]*>.*?</table>)',
        r'(<div\b[^>]*id=["\']ctl00_ctl00_cntMainBody_cntRosterBody_lblDienstkontext["\'][^>]*>.*?</div>)',
    ]

    parts = []
    for pattern in patterns:
        m = re.search(pattern, html_text, re.IGNORECASE | re.DOTALL)
        if m:
            parts.append(m.group(1))

    if not parts:
        m = re.search(r"(<body\b[^>]*>.*?</body>)", html_text, re.IGNORECASE | re.DOTALL)
        parts.append(m.group(1) if m else html_text)

    joined = "\n".join(parts)
    joined = html_lib.unescape(joined)
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def send_ntfy(message: str) -> None:
    resp = requests.post(
        NTFY_URL,
        data=message.encode("utf-8"),
        headers={
            "Title": "RNV Dienstplan",
            "Priority": "default",
            "Tags": "calendar,warning",
        },
        timeout=20,
    )
    resp.raise_for_status()


def main() -> int:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # 1) Login-Seite holen
        login_get = session.get(
            LOGIN_URL,
            headers={**HEADERS, "Referer": LOGIN_URL},
            timeout=30,
        )
        login_get.raise_for_status()

        hidden_fields = extract_hidden_fields(login_get.text)
        user_field, pass_field, submit_field, submit_value = infer_login_fields(login_get.text)

        payload = dict(hidden_fields)
        payload[user_field] = USERNAME
        payload[pass_field] = PASSWORD
        if submit_field:
            payload[submit_field] = submit_value

        # 2) Login absenden
        login_post = session.post(
            LOGIN_URL,
            data=payload,
            headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": ORIGIN,
                "Referer": LOGIN_URL,
            },
            timeout=30,
            allow_redirects=True,
        )
        login_post.raise_for_status()

        # 3) Dienstplan abrufen
        roster = session.get(
            ROSTER_URL,
            headers={**HEADERS, "Referer": LOGIN_URL},
            timeout=30,
        )
        roster.raise_for_status()

        html_text = roster.text
        if 'ctl00_ctl00_cntMainBody_calRoster' not in html_text:
            raise RuntimeError(
                "Dienstplan-Tabelle nicht gefunden. Login war vermutlich nicht erfolgreich."
            )

        current_content = extract_relevant_content(html_text)
        current_hash = hash_content(current_content)

        old_hash = STATE_FILE.read_text(encoding="utf-8").strip() if STATE_FILE.exists() else ""
        changed = bool(old_hash) and old_hash != current_hash

        if changed:
            send_ntfy("TEST BENACHRICHTIGUNG")
            print("[OK] Änderung erkannt, ntfy-Benachrichtigung gesendet.")
        elif not old_hash:
            print("[OK] Erster Lauf: Baseline gespeichert, keine Benachrichtigung.")
        else:
            print("[OK] Keine Änderung erkannt.")

        STATE_FILE.write_text(current_hash + "\n", encoding="utf-8")
        print(f"[INFO] Aktueller Hash: {current_hash}")

        return 0

    except requests.RequestException as exc:
        print(f"[HTTP-Fehler] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[Fehler] {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
