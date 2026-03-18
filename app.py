import os
import re
import hashlib
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

app = Flask(__name__)

CLUB_ID = "57920393"
LOGIN = os.environ.get("TENNIS_LOGIN", "JECHAP")
PASSWORD = os.environ.get("TENNIS_PASSWORD", "")
PARTNER_VALUE = "-100"  # Aurelien LANGE
PLANNING_URL = "https://www.premier-service.fr/5.11.04/ics.php"

JOURS_FR = {0:"Lundi",1:"Mardi",2:"Mercredi",3:"Jeudi",4:"Vendredi",5:"Samedi",6:"Dimanche"}


def get_md5(s):
    return hashlib.md5(s.upper().encode()).hexdigest()


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.premier-service.fr",
    })
    return s


def extract_fields(html):
    fl = fp = fm = idpge_val = action_url = None

    m = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', html, re.I)
    if m:
        action_url = m.group(1)

    for m in re.finditer(r'<input[^>]+type=["\']text["\'][^>]*>', html, re.I):
        nm = re.search(r'name=["\'](\w+)["\']', m.group(0))
        if nm and nm.group(1) not in ("userid",):
            fl = nm.group(1)
            break

    for m in re.finditer(r'<input[^>]+type=["\']password["\'][^>]*>', html, re.I):
        nm = re.search(r'name=["\'](\w+)["\']', m.group(0))
        if nm and nm.group(1) not in ("userkey",):
            fp = nm.group(1)
            break

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

    m = re.search(r'name=["\']idpge["\'][^>]+value=["\']([^"\']+)["\']', html, re.I)
    if not m:
        m = re.search(r'value=["\']([^"\']+)["\'][^>]+name=["\']idpge["\']', html, re.I)
    if m:
        idpge_val = m.group(1)

    return fl, fp, fm, idpge_val, action_url


def login():
    session = make_session()

    r0 = session.get(
        f"https://www.premier-service.fr/_start/index.php?club={CLUB_ID}",
        allow_redirects=True
    )

    r1 = session.post(PLANNING_URL, data={
        "club": CLUB_ID,
        "idact": "101",
    }, headers={"Referer": r0.url})

    html = r1.text
    fl, fp, fm, idpge_val, action_url = extract_fields(html)

    md5 = get_md5(PASSWORD + LOGIN)
    post_url = action_url if (action_url and action_url.startswith("http")) else PLANNING_URL
    # Normaliser l'URL (/../)
    post_url = post_url.replace("/_start/../5.11.04/", "/5.11.04/")

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

    session.headers["Referer"] = r1.url
    resp = session.post(post_url, data=payload)
    connected = ("fiche_identification" not in resp.text
                 and "fiche_erreur" not in resp.text
                 and len(resp.text) > 5000)

    return session, resp, connected


def format_date_fr(date_str):
    """Convertit JJ/MM/AAAA en 'JJ/MM/AAAA Jour'."""
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y")
        jour = JOURS_FR[dt.weekday()]
        return f"{date_str} {jour}"
    except:
        return date_str


def get_planning(session, date_str):
    date_fr = format_date_fr(date_str)
    payload = {
        "idact": "336",
        "idpge": "210-00000000000000",
        "IDOBJ": "10_0_2",
        "idses": "S0",
        "idcrt": "2",
        "idpro": "",
        "idpar": "",
        "pw": "14",
        "dj": "2",
        "userid": "",
        "usermd5": "",
        "club": "",
        "B_MOJJO": "0",
        "LISTE_RESA_BOURSE_DATE_JEU": "",
        "LISTE_RESA_BOURSE_HEURE_JEU": "",
        "LISTE_RESA_BOURSE_COURT_JEU": "",
        "CHAMP_SELECTEUR_JEU": "1",
        "ID_TABLEAU": f"1|{CLUB_ID}|1",
        "CHAMP_SELECTEUR_JOUR": date_fr,
        "nc": "30",
    }
    return session.post(PLANNING_URL, data=payload)


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
    session.post(PLANNING_URL, data={
        "idact": "332", "idpge": idpge,
        "IDOBJ": "100", "idpar": "100",
        "CHAMP_TYPE_1": PARTNER_VALUE,
        "idses": "S0", "b_i": "0",
    })
    return session.post(PLANNING_URL, data={
        "idact": "366", "idpge": idpge,
        "idses": "S0", "b_i": "0",
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/debug-login")
def debug_login():
    session, resp, connected = login()
    return jsonify({
        "connected": connected,
        "resp_len": len(resp.text),
        "html_preview": resp.text[:1000],
    })


@app.route("/debug-planning")
def debug_planning():
    date_str = request.args.get("date", "19/03/2026")
    session, _, connected = login()
    resp = get_planning(session, date_str)
    slots = parse_slots(resp.text)
    return jsonify({
        "connected": connected,
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

# Route temporaire pour voir le HTML après login
@app.route("/debug-after-login")
def debug_after_login():
    session, resp, connected = login()
    # Chercher idpge=210 dans le HTML
    html = resp.text
    m = re.search(r'idpge["\s]+value=["\']?(210-\d+)', html)
    idpge_210 = m.group(1) if m else "not found"
    # Chercher tous les idpge
    all_idpge = re.findall(r'idpge[^"\']*["\']([^"\']+)["\']', html)
    return jsonify({
        "connected": connected,
        "idpge_210": idpge_210,
        "all_idpge": all_idpge[:10],
        "html_snippet": html[html.find("210"):html.find("210")+200] if "210" in html else "not found",
        "html_preview": html[:3000],
    })
