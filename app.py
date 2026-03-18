import os
import re
import hashlib
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

app = Flask(__name__)

BASE_URL = "https://www.premier-service.fr/5.11.04/ics.php"
CLUB_ID = "32920393"

LOGIN = os.environ.get("TENNIS_LOGIN", "JECHAP")
PASSWORD = os.environ.get("TENNIS_PASSWORD", "")
PARTNER_VALUE = "-100"  # Aurelien LANGE


def get_md5(s):
    return hashlib.md5(s.upper().encode()).hexdigest()


def get_form_fields_from_js(html):
    field_login = None
    field_password = None
    field_md5 = None
    idpge_val = None

    login_match = re.search(
        r'document\.forms\[0\]\.\s*(\w+)\s*\n\s*\.focus\(\)',
        html
    )
    if login_match:
        field_login = login_match.group(1).strip()

    pwd_match = re.search(
        r'var pwd = document\.forms\[0\]\.\s*(\w+)\s*\n\s*\.',
        html
    )
    if pwd_match:
        field_password = pwd_match.group(1).strip()

    md5_match = re.search(
        r'document\.forms\[0\]\.\s*(\w+)\s*\n\s*\.\s*\n\s*value\s*=\s*md5',
        html
    )
    if md5_match:
        field_md5 = md5_match.group(1).strip()

    idpge_match = re.search(r'name="idpge"\s+value="([^"]+)"', html)
    if idpge_match:
        idpge_val = idpge_match.group(1)

    return field_login, field_password, field_md5, idpge_val


def login():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.premier-service.fr",
    })

    # Étape 1 : simuler le POST automatique de adsltennis.fr vers premier-service.fr
    # (ce que fait idgfrm.submit() en JS)
    step1 = session.post(BASE_URL, data={
        "club": CLUB_ID,
        "idact": "101",
    })

    # Étape 2 : extraire les champs dynamiques du vrai formulaire de login
    fl, fp, fm, idpge_val = get_form_fields_from_js(step1.text)

    md5 = get_md5(PASSWORD + LOGIN)

    payload = {
        "idact": "101",
        "idpge": idpge_val or f"101-{CLUB_ID}",
        "usermd5": "",
        "idgfcmiid": "0",
        "largeur_ecran": "1536",
        "hauteur_ecran": "864",
        "pingmax": "401",
        "pingmin": "18",
        "userid": "",
        "userkey": "",
    }

    if fl:
        payload[fl] = LOGIN
    if fp:
        payload[fp] = ""
    if fm:
        payload[fm] = md5

    debug = {
        "field_login": fl, "field_password": fp,
        "field_md5": fm, "idpge_val": idpge_val,
        "md5": md5, "step1_url": step1.url,
        "step1_length": len(step1.text),
    }

    resp = session.post(BASE_URL, data=payload)
    return session, resp, debug


def get_planning(session, date_str):
    payload = {"idact": "345", "ladate": date_str, "idses": "S0"}
    return session.post(BASE_URL, data=payload)


def parse_slots(html):
    soup = BeautifulSoup(html, "lxml")
    slots = []
    for tag in soup.find_all(onclick=True):
        onclick = tag.get("onclick", "")
        if "330" in onclick:
            label = tag.get_text(strip=True)
            m = re.search(r"idpge['\"]?\s*[:=]\s*['\"]?([^'\"&,\s;]+)", onclick)
            idpge = m.group(1) if m else ""
            slots.append({"label": label, "idpge": idpge, "onclick_raw": onclick[:300]})
    return slots


def validate_reservation(session, idpge):
    session.post(BASE_URL, data={
        "idact": "332", "idpge": idpge,
        "IDOBJ": "100", "idpar": "100",
        "CHAMP_TYPE_1": PARTNER_VALUE,
        "idses": "S0", "b_i": "0",
    })
    return session.post(BASE_URL, data={
        "idact": "366", "idpge": idpge,
        "idses": "S0", "b_i": "0",
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/debug-login")
def debug_login():
    session, resp, debug = login()
    connected = "fiche_identification" not in resp.text
    return jsonify({
        "connected": connected,
        "debug": debug,
        "html_preview": resp.text[:3000],
    })


@app.route("/debug-init")
def debug_init():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    step1 = session.post(BASE_URL, data={"club": CLUB_ID, "idact": "101"})
    html = step1.text
    idx = html.find("fsmd5")
    snippet = html[max(0, idx-300):idx+600] if idx > -1 else "fsmd5 not found"
    return jsonify({
        "url": step1.url,
        "html_length": len(html),
        "fsmd5_snippet": snippet,
        "form_snippet": html[html.find("<form"):html.find("<form")+2000] if "<form" in html else "no form",
    })


@app.route("/debug-planning")
def debug_planning():
    date_str = request.args.get("date", "20/03/2026")
    session, login_resp, debug = login()
    resp = get_planning(session, date_str)
    return jsonify({
        "debug": debug,
        "connected": "fiche_identification" not in login_resp.text,
        "planning_length": len(resp.text),
        "planning_html": resp.text[:8000],
    })


@app.route("/creneaux")
def creneaux():
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Parametre 'date' manquant"}), 400
    session, _, _ = login()
    resp = get_planning(session, date_str)
    slots = parse_slots(resp.text)
    return jsonify({"date": date_str, "creneaux": slots, "html_length": len(resp.text)})


@app.route("/reserver", methods=["POST"])
def reserver():
    data = request.json
    idpge = data.get("idpge")
    if not idpge:
        return jsonify({"error": "idpge manquant"}), 400
    session, _, _ = login()
    resp = validate_reservation(session, idpge)
    soup = BeautifulSoup(resp.text, "lxml")
    erreur = soup.find(class_="erreur")
    if erreur and erreur.get_text(strip=True):
        return jsonify({"error": erreur.get_text(strip=True)})
    return jsonify({"status": "ok", "message": "Reservation confirmee"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
