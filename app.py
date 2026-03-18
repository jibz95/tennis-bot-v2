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


def make_session(phpsessid=None):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.premier-service.fr",
        "Referer": BASE_URL,
    })
    if phpsessid:
        session.cookies.set("PHPSESSID", phpsessid, domain="www.premier-service.fr")
    return session


def login_with_cookie(phpsessid):
    """Utilise un PHPSESSID existant."""
    session = make_session(phpsessid)
    # Vérifier que la session est valide
    resp = session.post(BASE_URL, data={"idact": "345", "idses": "S0"})
    connected = "fiche_identification" not in resp.text and "session" not in resp.text.lower()[:500]
    return session, connected, resp


def login_fresh():
    """Login complet depuis zéro via le flow adsltennis -> premier-service."""
    session = make_session()

    # Étape 1 : GET adsltennis pour obtenir PHPSESSID initial
    r0 = session.get(
        f"https://www.adsltennis.fr/_start/index.php?club={CLUB_ID}&idact=101",
        allow_redirects=False
    )

    # Étape 2 : suivre la redirection manuellement vers premier-service
    location = r0.headers.get("Location", "")
    if location:
        r1 = session.get(location, allow_redirects=True)
    else:
        r1 = session.post(BASE_URL, data={"club": CLUB_ID, "idact": "101"})

    # Étape 3 : extraire les champs dynamiques du formulaire
    html = r1.text
    fl, fp, fm, idpge_val = extract_fields(html)

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
    if fl: payload[fl] = LOGIN
    if fp: payload[fp] = ""
    if fm: payload[fm] = md5

    resp = session.post(BASE_URL, data=payload)
    connected = "fiche_identification" not in resp.text

    debug = {
        "field_login": fl, "field_md5": fm,
        "idpge_val": idpge_val, "md5": md5,
        "r0_status": r0.status_code,
        "r0_location": location,
        "r1_url": r1.url,
        "r1_length": len(html),
        "cookies": dict(session.cookies),
    }
    return session, connected, resp, debug


def extract_fields(html):
    fl = fp = fm = idpge_val = None

    m = re.search(r'document\.forms\[0\]\.\s*(\w+)\s*\n\s*\.focus\(\)', html)
    if m: fl = m.group(1).strip()

    m = re.search(r'var pwd = document\.forms\[0\]\.\s*(\w+)\s*\n', html)
    if m: fp = m.group(1).strip()

    m = re.search(r'document\.forms\[0\]\.\s*(\w+)\s*\n\s*\.\s*\n\s*value\s*=\s*md5', html)
    if m: fm = m.group(1).strip()

    m = re.search(r'name="idpge"\s+value="([^"]+)"', html)
    if m: idpge_val = m.group(1)

    return fl, fp, fm, idpge_val


def get_planning(session, date_str):
    return session.post(BASE_URL, data={"idact": "345", "ladate": date_str, "idses": "S0"})


def parse_slots(html):
    soup = BeautifulSoup(html, "lxml")
    slots = []
    for tag in soup.find_all(onclick=True):
        onclick = tag.get("onclick", "")
        if "330" in onclick:
            label = tag.get_text(strip=True)
            m = re.search(r"idpge['\"]?\s*[:=]\s*['\"]?([^'\"&,\s;]+)", onclick)
            slots.append({"label": label, "idpge": m.group(1) if m else "", "onclick_raw": onclick[:300]})
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
    phpsessid = request.args.get("phpsessid")
    if phpsessid:
        session, connected, resp = login_with_cookie(phpsessid)
        return jsonify({"method": "cookie", "connected": connected, "html_preview": resp.text[:1000]})
    else:
        session, connected, resp, debug = login_fresh()
        return jsonify({"method": "fresh", "connected": connected, "debug": debug, "html_preview": resp.text[:1000]})


@app.route("/debug-planning")
def debug_planning():
    date_str = request.args.get("date", "20/03/2026")
    phpsessid = request.args.get("phpsessid")

    if phpsessid:
        session = make_session(phpsessid)
    else:
        session, connected, _, debug = login_fresh()

    resp = get_planning(session, date_str)
    slots = parse_slots(resp.text)
    return jsonify({
        "planning_length": len(resp.text),
        "slots_found": len(slots),
        "slots": slots[:5],
        "planning_html": resp.text[:5000],
    })


@app.route("/creneaux")
def creneaux():
    date_str = request.args.get("date")
    phpsessid = request.args.get("phpsessid")
    if not date_str:
        return jsonify({"error": "Parametre 'date' manquant"}), 400

    if phpsessid:
        session = make_session(phpsessid)
    else:
        session, _, _, _ = login_fresh()

    resp = get_planning(session, date_str)
    slots = parse_slots(resp.text)
    return jsonify({"date": date_str, "creneaux": slots})


@app.route("/reserver", methods=["POST"])
def reserver():
    data = request.json
    idpge = data.get("idpge")
    phpsessid = data.get("phpsessid")
    if not idpge:
        return jsonify({"error": "idpge manquant"}), 400

    if phpsessid:
        session = make_session(phpsessid)
    else:
        session, _, _, _ = login_fresh()

    resp = validate_reservation(session, idpge)
    soup = BeautifulSoup(resp.text, "lxml")
    erreur = soup.find(class_="erreur")
    if erreur and erreur.get_text(strip=True):
        return jsonify({"error": erreur.get_text(strip=True)})
    return jsonify({"status": "ok", "message": "Reservation confirmee"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
