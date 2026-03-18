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


def get_form_fields(html):
    """Extrait les noms de champs dynamiques depuis le HTML de la page de login."""
    soup = BeautifulSoup(html, "lxml")
    
    field_login = None
    field_password = None
    field_md5 = None
    field_idpge = None
    idpge_val = ""

    form = soup.find("form")
    if not form:
        return None, None, None, None, ""

    fixed_names = {"idact", "usermd5", "idgfcmiid", "largeur_ecran", "hauteur_ecran",
                   "pingmax", "pingmin", "userid", "userkey", "idses", "b_i"}

    for inp in form.find_all("input"):
        name = inp.get("name", "")
        itype = inp.get("type", "text")
        val = inp.get("value", "")

        if not name or name in fixed_names:
            continue

        if itype == "text":
            field_login = name
        elif itype == "password":
            field_password = name
        elif itype == "hidden":
            if "pge" in name.lower() and val:
                field_idpge = name
                idpge_val = val
            elif not val:
                field_md5 = name

    return field_login, field_password, field_md5, field_idpge, idpge_val


def login():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.premier-service.fr",
    })

    # Charger la page de login — suivre les redirections pour arriver sur premier-service.fr
    init_resp = session.get(
        f"https://www.adsltennis.fr/_start/index.php?club={CLUB_ID}&idact=101",
        allow_redirects=True
    )

    # Parser les champs depuis la page finale (après redirections)
    fl, fp, fm, fidpge, idpge_val = get_form_fields(init_resp.text)

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
        "field_md5": fm, "field_idpge": fidpge,
        "idpge_val": idpge_val, "md5": md5,
        "init_url": init_resp.url,
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
    # Chercher si on est connecté (présence du planning ou d'un menu)
    connected = "fiche_identification" not in resp.text
    return jsonify({
        "connected": connected,
        "status_code": resp.status_code,
        "debug": debug,
        "html_preview": resp.text[:2000],
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
