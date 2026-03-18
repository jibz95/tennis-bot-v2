import os
import re
import hashlib
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

app = Flask(__name__)

START_URL = "https://www.premier-service.fr/_start/ics.php"
CLUB_ID = "32920393"

LOGIN = os.environ.get("TENNIS_LOGIN", "JECHAP")
PASSWORD = os.environ.get("TENNIS_PASSWORD", "")
PARTNER_VALUE = "-100"  # Aurelien LANGE


def get_md5(s):
    return hashlib.md5(s.upper().encode()).hexdigest()


def extract_fields(html):
    """Extrait les champs dynamiques depuis le HTML du formulaire de login."""
    fl = fp = fm = idpge_val = action_url = None

    # Champ identifiant (input type=text visible, pas userid)
    m = re.search(r'<input[^>]+type=["\']text["\'][^>]+name=["\'](\w+)["\']', html)
    if m and m.group(1) not in ("userid",):
        fl = m.group(1)

    # Champ password
    m = re.search(r'<input[^>]+type=["\']password["\'][^>]+name=["\'](\w+)["\']', html)
    if m and m.group(1) not in ("userkey",):
        fp = m.group(1)

    # Champ MD5 : hidden sans value, pas dans la liste fixe
    fixed = {"idact", "usermd5", "idgfcmiid", "largeur_ecran", "hauteur_ecran",
             "pingmax", "pingmin", "userid", "userkey", "idses"}
    for m in re.finditer(r'<input[^>]+type=["\']hidden["\'][^>]+name=["\'](\w+)["\'][^>]*>', html):
        name = m.group(1)
        val_m = re.search(r'value=["\']([^"\']*)["\']', m.group(0))
        val = val_m.group(1) if val_m else ""
        if name not in fixed and not val:
            fm = name
            break

    # idpge
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\']([^"\']+)["\']', html)
    if m:
        idpge_val = m.group(1)

    # action URL du form
    m = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', html)
    if m:
        action_url = m.group(1)

    return fl, fp, fm, idpge_val, action_url


def login():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.premier-service.fr",
    })

    # Charger la page de login via adsltennis
    r0 = session.get(
        f"https://www.adsltennis.fr/_start/index.php?club={CLUB_ID}&idact=101",
        allow_redirects=True
    )
    html = r0.text
    fl, fp, fm, idpge_val, action_url = extract_fields(html)

    # Fallback : essayer l'URL _start directement
    if not fl and not fm:
        r1 = session.get(START_URL, params={"club": CLUB_ID, "idact": "101"})
        html = r1.text
        fl, fp, fm, idpge_val, action_url = extract_fields(html)

    md5 = get_md5(PASSWORD + LOGIN)
    post_url = action_url if action_url and action_url.startswith("http") else START_URL

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

    resp = session.post(post_url, data=payload)
    connected = "fiche_identification" not in resp.text and "fiche_erreur" not in resp.text

    debug = {
        "field_login": fl, "field_md5": fm,
        "idpge_val": idpge_val, "post_url": post_url,
        "md5": md5, "r0_url": r0.url,
        "html_snippet": html[html.find("<form"):html.find("<form")+500] if "<form" in html else "no form",
        "cookies": dict(session.cookies),
        "connected": connected,
    }
    return session, resp, debug


def get_planning(session, date_str):
    return session.post(START_URL, data={"idact": "345", "ladate": date_str, "idses": "S0"})


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
    session.post(START_URL, data={
        "idact": "332", "idpge": idpge,
        "IDOBJ": "100", "idpar": "100",
        "CHAMP_TYPE_1": PARTNER_VALUE,
        "idses": "S0", "b_i": "0",
    })
    return session.post(START_URL, data={
        "idact": "366", "idpge": idpge,
        "idses": "S0", "b_i": "0",
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/debug-login")
def debug_login():
    session, resp, debug = login()
    return jsonify({
        "connected": debug["connected"],
        "debug": debug,
        "html_preview": resp.text[:1500],
    })


@app.route("/debug-planning")
def debug_planning():
    date_str = request.args.get("date", "19/03/2026")
    session, _, debug = login()
    resp = get_planning(session, date_str)
    slots = parse_slots(resp.text)
    return jsonify({
        "connected": debug["connected"],
        "planning_length": len(resp.text),
        "slots_found": len(slots),
        "slots": slots[:10],
        "planning_html": resp.text[:5000],
    })


@app.route("/creneaux")
def creneaux():
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Parametre 'date' manquant"}), 400
    session, _, _ = login()
    resp = get_planning(session, date_str)
    slots = parse_slots(resp.text)
    return jsonify({"date": date_str, "creneaux": slots})


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
