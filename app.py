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


def login():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.premier-service.fr",
        "Referer": f"https://www.adsltennis.fr/_start/index.php?club={CLUB_ID}&idact=101",
    })

    # Étape 1 : charger la page de login pour récupérer les noms de champs dynamiques
    init_resp = session.get(
        f"https://www.adsltennis.fr/_start/index.php?club={CLUB_ID}&idact=101"
    )

    # Étape 2 : parser les noms de champs depuis le HTML
    soup = BeautifulSoup(init_resp.text, "lxml")
    form = soup.find("form")

    # Trouver le champ identifiant (input type=text visible)
    field_login = None
    field_password = None
    field_md5 = None
    field_idpge = None

    if form:
        for inp in form.find_all("input"):
            name = inp.get("name", "")
            itype = inp.get("type", "text")
            if itype == "text" and name and name not in ["userid", "largeur_ecran", "hauteur_ecran"]:
                field_login = name
            elif itype == "password" and name:
                field_password = name
            elif itype == "hidden" and name and "pge" in name.lower():
                field_idpge = name
        # Le champ MD5 est le hidden sans valeur initiale qui n'est pas usermd5/idgfcmiid
        for inp in form.find_all("input", {"type": "hidden"}):
            name = inp.get("name", "")
            val = inp.get("value", "")
            if not val and name and name not in ["usermd5", "idgfcmiid", "userid", "userkey", "idact"]:
                if name != field_idpge:
                    field_md5 = name

    # Récupérer idpge depuis la page
    idpge_val = ""
    if field_idpge and form:
        idpge_inp = form.find("input", {"name": field_idpge})
        if idpge_inp:
            idpge_val = idpge_inp.get("value", f"101-{CLUB_ID}")

    # Calcul MD5 : (PASSWORD + LOGIN).toUpperCase()
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

    if field_login:
        payload[field_login] = LOGIN
    if field_password:
        payload[field_password] = ""
    if field_md5:
        payload[field_md5] = md5

    resp = session.post(BASE_URL, data=payload)
    return session, resp, {
        "field_login": field_login,
        "field_password": field_password,
        "field_md5": field_md5,
        "field_idpge": field_idpge,
        "idpge_val": idpge_val,
        "md5": md5,
    }


def get_planning(session, date_str):
    payload = {
        "idact": "345",
        "ladate": date_str,
        "idses": "S0",
    }
    resp = session.post(BASE_URL, data=payload)
    return resp


def parse_slots(html):
    soup = BeautifulSoup(html, "lxml")
    slots = []
    for tag in soup.find_all(onclick=True):
        onclick = tag.get("onclick", "")
        if "330" in onclick:
            label = tag.get_text(strip=True)
            idpge_match = re.search(r"idpge['\"]?\s*[:=]\s*['\"]?([^'\"&,\s;]+)", onclick)
            idpge = idpge_match.group(1) if idpge_match else ""
            slots.append({
                "label": label,
                "idpge": idpge,
                "onclick_raw": onclick[:300]
            })
    return slots


def validate_reservation(session, idpge):
    payload_partner = {
        "idact": "332",
        "idpge": idpge,
        "IDOBJ": "100",
        "idpar": "100",
        "CHAMP_TYPE_1": PARTNER_VALUE,
        "idses": "S0",
        "b_i": "0",
    }
    session.post(BASE_URL, data=payload_partner)
    payload_validate = {
        "idact": "366",
        "idpge": idpge,
        "idses": "S0",
        "b_i": "0",
    }
    return session.post(BASE_URL, data=payload_validate)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/debug-login")
def debug_login():
    session, resp, debug = login()
    return jsonify({
        "status_code": resp.status_code,
        "url_finale": resp.url,
        "cookies": dict(session.cookies),
        "debug_fields": debug,
        "html_preview": resp.text[:2000],
    })


@app.route("/debug-planning")
def debug_planning():
    date_str = request.args.get("date", "20/03/2026")
    session, login_resp, debug = login()
    resp = get_planning(session, date_str)
    return jsonify({
        "debug_fields": debug,
        "login_preview": login_resp.text[:300],
        "planning_status": resp.status_code,
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
    return jsonify({
        "date": date_str,
        "creneaux": slots,
        "html_length": len(resp.text)
    })


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
