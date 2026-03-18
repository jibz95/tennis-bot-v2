import os
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    session.get(BASE_URL)
    md5 = get_md5(PASSWORD + LOGIN)
    payload = {
        "idact": "101",
        "idpge": f"101-{CLUB_ID}",
        "usermd5": "",
        "vesiaifeytketradmeus": md5,
        "idgfcmiid": "0",
        "largeur_ecran": "1536",
        "hauteur_ecran": "864",
        "pingmax": "401",
        "pingmin": "18",
        "userid": "",
        "userkey": "",
        "rpaaeddpyyiuhs": LOGIN,
        "ryusakurjstoeenf": "",
    }
    resp = session.post(BASE_URL, data=payload)
    return session, resp


def get_planning(session, date_str):
    payload = {"idact": "345", "ladate": date_str, "idses": "S0"}
    resp = session.post(BASE_URL, data=payload)
    return resp


def parse_slots(html):
    import re
    soup = BeautifulSoup(html, "lxml")
    slots = []
    for tag in soup.find_all(onclick=True):
        onclick = tag.get("onclick", "")
        if "330" in onclick:
            label = tag.get_text(strip=True)
            idpge_match = re.search(r"idpge['\"]?\s*[:=]\s*['\"]?([^'\"&,\s;]+)", onclick)
            idpge = idpge_match.group(1) if idpge_match else ""
            slots.append({"label": label, "idpge": idpge, "onclick_raw": onclick[:300]})
    return slots


def validate_reservation(session, idpge):
    payload_partner = {
        "idact": "332", "idpge": idpge,
        "IDOBJ": "100", "idpar": "100",
        "CHAMP_TYPE_1": PARTNER_VALUE,
        "idses": "S0", "b_i": "0",
    }
    session.post(BASE_URL, data=payload_partner)
    payload_validate = {
        "idact": "366", "idpge": idpge,
        "idses": "S0", "b_i": "0",
    }
    return session.post(BASE_URL, data=payload_validate)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/debug-login")
def debug_login():
    session, resp = login()
    return jsonify({
        "status_code": resp.status_code,
        "html_preview": resp.text[:3000],
        "cookies": dict(session.cookies),
    })


@app.route("/debug-planning")
def debug_planning():
    date_str = request.args.get("date", "20/03/2026")
    session, _ = login()
    resp = get_planning(session, date_str)
    return jsonify({
        "status_code": resp.status_code,
        "html_length": len(resp.text),
        "html": resp.text[:8000],
    })


@app.route("/creneaux")
def creneaux():
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Parametre 'date' manquant"}), 400
    session, _ = login()
    resp = get_planning(session, date_str)
    slots = parse_slots(resp.text)
    return jsonify({"date": date_str, "creneaux": slots, "html_length": len(resp.text)})


@app.route("/reserver", methods=["POST"])
def reserver():
    data = request.json
    idpge = data.get("idpge")
    if not idpge:
        return jsonify({"error": "idpge manquant"}), 400
    session, _ = login()
    resp = validate_reservation(session, idpge)
    soup = BeautifulSoup(resp.text, "lxml")
    erreur = soup.find(class_="erreur")
    if erreur and erreur.get_text(strip=True):
        return jsonify({"error": erreur.get_text(strip=True)})
    return jsonify({"status": "ok", "message": "Reservation confirmee"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
