import os
import re
import hashlib
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

app = Flask(__name__)

CLUB_ID = "32920393"
LOGIN = os.environ.get("TENNIS_LOGIN", "JECHAP")
PASSWORD = os.environ.get("TENNIS_PASSWORD", "")
PARTNER_VALUE = "-100"  # Aurelien LANGE


def get_md5(s):
    return hashlib.md5(s.upper().encode()).hexdigest()


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    return s


def login():
    session = make_session()

    # Étape 1 : charger la page _start pour obtenir le PHPSESSID
    r0 = session.get(
        f"https://www.adsltennis.fr/_start/index.php?club={CLUB_ID}&idact=101",
        allow_redirects=True
    )

    # La page adsltennis redirige vers premier-service.fr/_start/index.php
    # qui contient le vrai formulaire de login
    html = r0.text

    # Extraire les champs depuis le HTML
    fl, fp, fm, idpge_val, action_url = extract_fields(html)

    md5 = get_md5(PASSWORD + LOGIN)

    # Construire l'URL de POST
    if action_url:
        if action_url.startswith("http"):
            post_url = action_url
        else:
            base = r0.url.rsplit("/", 1)[0]
            post_url = base + "/" + action_url.lstrip("/")
    else:
        post_url = "https://www.premier-service.fr/_start/ics.php"

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

    session.headers["Referer"] = r0.url
    session.headers["Origin"] = "https://www.premier-service.fr"

    resp = session.post(post_url, data=payload)
    connected = ("fiche_identification" not in resp.text
                 and "fiche_erreur" not in resp.text
                 and "404" not in resp.text[:200])

    debug = {
        "field_login": fl, "field_md5": fm,
        "idpge_val": idpge_val, "post_url": post_url,
        "action_url": action_url,
        "md5": md5, "r0_url": r0.url,
        "r0_length": len(html),
        "cookies": dict(session.cookies),
        "connected": connected,
        "resp_url": resp.url,
        "resp_length": len(resp.text),
    }
    return session, resp, debug


def extract_fields(html):
    fl = fp = fm = idpge_val = action_url = None

    # Action URL
    m = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', html, re.I)
    if m:
        action_url = m.group(1)

    # Champ login (text visible, pas userid)
    for m in re.finditer(r'<input[^>]+type=["\']text["\'][^>]*>', html, re.I):
        nm = re.search(r'name=["\'](\w+)["\']', m.group(0))
        if nm and nm.group(1) not in ("userid",):
            fl = nm.group(1)
            break

    # Champ password (pas userkey)
    for m in re.finditer(r'<input[^>]+type=["\']password["\'][^>]*>', html, re.I):
        nm = re.search(r'name=["\'](\w+)["\']', m.group(0))
        if nm and nm.group(1) not in ("userkey",):
            fp = nm.group(1)
            break

    # Champ MD5 : hidden sans valeur, hors liste fixe
    fixed = {"idact", "usermd5", "idgfcmiid", "largeur_ecran", "hauteur_ecran",
             "pingmax", "pingmin", "userid", "userkey", "idses", "b_i", "club"}
    for m in re.finditer(r'<input[^>]+type=["\']hidden["\'][^>]*>', html, re.I):
        nm = re.search(r'name=["\'](\w+)["\']', m.group(0))
        if not nm:
            continue
        name = nm.group(1)
        vm = re.search(r'value=["\']([^"\']*)["\']', m.group(0))
        val = vm.group(1) if vm else ""
        if name not in fixed and not val:
            fm = name
            break

    # idpge
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\']([^"\']+)["\']', html, re.I)
    if not m:
        m = re.search(r'value=["\']([^"\']+)["\'][^>]+name=["\']idpge["\']', html, re.I)
    if m:
        idpge_val = m.group(1)

    return fl, fp, fm, idpge_val, action_url


def get_planning(session, date_str):
    return session.post(
        "https://www.premier-service.fr/_start/ics.php",
        data={"idact": "345", "ladate": date_str, "idses": "S0"}
    )


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
    url = "https://www.premier-service.fr/_start/ics.php"
    session.post(url, data={
        "idact": "332", "idpge": idpge,
        "IDOBJ": "100", "idpar": "100",
        "CHAMP_TYPE_1": PARTNER_VALUE,
        "idses": "S0", "b_i": "0",
    })
    return session.post(url, data={
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
        "html_preview": resp.text[:2000],
    })


@app.route("/debug-r0")
def debug_r0():
    """Voir le HTML brut de la page de login après redirections."""
    session = make_session()
    r0 = session.get(
        f"https://www.adsltennis.fr/_start/index.php?club={CLUB_ID}&idact=101",
        allow_redirects=True
    )
    html = r0.text
    return jsonify({
        "url": r0.url,
        "length": len(html),
        "has_form": "<form" in html,
        "form_snippet": html[html.find("<form"):html.find("<form")+1500] if "<form" in html else "no form",
        "html_start": html[:500],
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
