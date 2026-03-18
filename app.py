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
PARTNER_VALUE = "-100"
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


def extract_login_fields(html):
    fl = fp = fm = idpge_val = action_url = None
    m = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', html, re.I)
    if m: action_url = m.group(1)
    for m in re.finditer(r'<input[^>]+type=["\']text["\'][^>]*>', html, re.I):
        nm = re.search(r'name=["\'](\w+)["\']', m.group(0))
        if nm and nm.group(1) not in ("userid",): fl = nm.group(1); break
    for m in re.finditer(r'<input[^>]+type=["\']password["\'][^>]*>', html, re.I):
        nm = re.search(r'name=["\'](\w+)["\']', m.group(0))
        if nm and nm.group(1) not in ("userkey",): fp = nm.group(1); break
    fixed = {"idact","usermd5","idgfcmiid","largeur_ecran","hauteur_ecran",
             "pingmax","pingmin","userid","userkey","idses","b_i","club"}
    for m in re.finditer(r'<input[^>]+type=["\']hidden["\'][^>]*>', html, re.I):
        nm = re.search(r'name=["\'](\w+)["\']', m.group(0))
        if not nm: continue
        name = nm.group(1)
        vm = re.search(r'value=["\']([^"\']*)["\']', m.group(0))
        val = vm.group(1) if vm else ""
        if name not in fixed and not val: fm = name; break
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\']([^"\']+)["\']', html, re.I)
    if not m: m = re.search(r'value=["\']([^"\']+)["\'][^>]+name=["\']idpge["\']', html, re.I)
    if m: idpge_val = m.group(1)
    return fl, fp, fm, idpge_val, action_url


def login():
    session = make_session()
    r0 = session.get(f"https://www.premier-service.fr/_start/index.php?club={CLUB_ID}", allow_redirects=True)
    r1 = session.post(PLANNING_URL, data={"club": CLUB_ID, "idact": "101"}, headers={"Referer": r0.url})
    html = r1.text
    fl, fp, fm, idpge_val, action_url = extract_login_fields(html)
    md5 = get_md5(PASSWORD + LOGIN)
    post_url = (action_url or PLANNING_URL).replace("/_start/../5.11.04/", "/5.11.04/").replace("?", "")
    payload = {
        "idact": "101", "idpge": idpge_val or f"101-{CLUB_ID}",
        "usermd5": "", "idgfcmiid": "0",
        "largeur_ecran": "1536", "hauteur_ecran": "864",
        "pingmax": "401", "pingmin": "18", "userid": "", "userkey": "",
    }
    if fl: payload[fl] = LOGIN
    if fp: payload[fp] = ""
    if fm: payload[fm] = md5
    session.headers["Referer"] = r1.url
    resp = session.post(post_url, data=payload)
    connected = "fiche_identification" not in resp.text and len(resp.text) > 5000
    return session, resp, connected


def format_date_fr(date_str):
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y")
        return f"{date_str} {JOURS_FR[dt.weekday()]}"
    except:
        return date_str


def get_planning(session, login_resp, date_str):
    """Navigue vers une date en utilisant idact=336."""
    # Extraire idpge du planning depuis la réponse du login
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\'](\d+-\d+)["\']', login_resp.text)
    if not m:
        m = re.search(r'value=["\'](\d+-\d+)["\'][^>]+name=["\']idpge["\']', login_resp.text)
    planning_idpge = m.group(1) if m else f"210-{CLUB_ID}"

    # Extraire IDOBJ courant
    m2 = re.search(r'name=["\']IDOBJ["\'][^>]*value=["\']([^"\']*)["\']', login_resp.text)
    idobj = m2.group(1) if m2 else "10_0_2"

    # Extraire idcrt
    m3 = re.search(r'name=["\']idcrt["\'][^>]*value=["\']([^"\']*)["\']', login_resp.text)
    idcrt = m3.group(1) if m3 else "2"

    date_fr = format_date_fr(date_str)
    payload = {
        "idact": "336",
        "idpge": planning_idpge,
        "IDOBJ": idobj,
        "idses": "S0", "idcrt": idcrt,
        "idpro": "", "idpar": "",
        "pw": "24", "dj": "2",
        "userid": "", "usermd5": "", "club": "",
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
    """
    Les créneaux libres sont des <td> avec onclick contenant IDOBJ.value et idact=336.
    Le clic sur un créneau soumet idact=336 avec l'IDOBJ du créneau.
    On cherche les cellules dont le texte est une heure (ex: 9h, 10h) 
    et qui ont un onclick avec IDOBJ.
    """
    soup = BeautifulSoup(html, "lxml")
    slots = []

    for td in soup.find_all("td"):
        onclick = td.get("onclick", "")
        if not onclick:
            continue

        # Chercher IDOBJ dans onclick
        idobj_m = re.search(r"IDOBJ\.value='([^']+)'", onclick)
        if not idobj_m:
            continue

        idobj = idobj_m.group(1)
        text = td.get_text(strip=True)

        # Les créneaux libres ont juste une heure comme texte (ex: "9h", "10h", "15h")
        if not re.match(r'^\d{1,2}h\d*$', text):
            continue

        # Extraire idcrt
        idcrt_m = re.search(r"idcrt\.value='([^']+)'", onclick)
        pw_m = re.search(r"pw\.value='([^']+)'", onclick)
        idcrt = idcrt_m.group(1) if idcrt_m else "2"
        pw = pw_m.group(1) if pw_m else "24"

        # Décoder IDOBJ: format site_?_court_heure ou site_?_court
        parts = idobj.split("_")
        court_num = parts[2] if len(parts) > 2 else "?"

        slots.append({
            "label": f"Court {court_num} - {text}",
            "heure": text,
            "court": court_num,
            "idobj": idobj,
            "idcrt": idcrt,
            "pw": pw,
        })

    return slots


def open_reservation_form(session, login_resp, idobj, idcrt, pw):
    """Clique sur un créneau libre — soumet idact=336 avec l'IDOBJ du créneau."""
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\'](\d+-\d+)["\']', login_resp.text)
    if not m:
        m = re.search(r'value=["\'](\d+-\d+)["\'][^>]+name=["\']idpge["\']', login_resp.text)
    planning_idpge = m.group(1) if m else f"210-{CLUB_ID}"

    today = datetime.now().strftime("%d/%m/%Y")
    date_fr = format_date_fr(today)

    payload = {
        "idact": "336",
        "idpge": planning_idpge,
        "IDOBJ": idobj,
        "idses": "S0", "idcrt": idcrt,
        "idpro": "", "idpar": "",
        "pw": pw, "dj": "2",
        "userid": "", "usermd5": "", "club": "",
        "B_MOJJO": "0",
        "CHAMP_SELECTEUR_JEU": "1",
        "ID_TABLEAU": f"1|{CLUB_ID}|1",
        "CHAMP_SELECTEUR_JOUR": date_fr,
        "nc": "30",
    }
    return session.post(PLANNING_URL, data=payload)


def select_partner_and_validate(session, fiche_resp):
    """Sélectionne Aurelien LANGE et valide."""
    fiche_html = fiche_resp.text
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\']([^"\']+)["\']', fiche_html)
    if not m:
        m = re.search(r'value=["\']([^"\']+)["\'][^>]+name=["\']idpge["\']', fiche_html)
    idpge = m.group(1) if m else ""

    session.post(PLANNING_URL, data={
        "idact": "332", "idpge": idpge,
        "IDOBJ": "100", "IDREF": "", "idtpa": "",
        "idpar": "100", "rcout": "", "b_i": "0",
        "idses": "S0", "CHAMP_TYPE_1": PARTNER_VALUE,
    })
    return session.post(PLANNING_URL, data={
        "idact": "366", "idpge": idpge,
        "IDOBJ": "", "IDREF": "", "idtpa": "",
        "idpar": "", "rcout": "", "b_i": "0", "idses": "S0",
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/debug-login")
def debug_login():
    session, resp, connected = login()
    return jsonify({"connected": connected, "resp_len": len(resp.text), "html_preview": resp.text[:500]})


@app.route("/debug-planning")
def debug_planning():
    date_str = request.args.get("date", datetime.now().strftime("%d/%m/%Y"))
    session, login_resp, connected = login()
    today = datetime.now().strftime("%d/%m/%Y")
    if date_str == today:
        html = login_resp.text
    else:
        resp = get_planning(session, login_resp, date_str)
        html = resp.text
    slots = parse_slots(html)
    # Debug: chercher tous les onclick avec IDOBJ
    all_onclick = re.findall(r"IDOBJ\.value='([^']+)'", html)
    return jsonify({
        "connected": connected,
        "planning_length": len(html),
        "slots_found": len(slots),
        "slots": slots[:10],
        "all_idobj_found": all_onclick[:20],
    })


@app.route("/creneaux")
def creneaux():
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Parametre 'date' manquant"}), 400
    session, login_resp, _ = login()
    today = datetime.now().strftime("%d/%m/%Y")
    if date_str == today:
        html = login_resp.text
    else:
        resp = get_planning(session, login_resp, date_str)
        html = resp.text
    slots = parse_slots(html)
    return jsonify({"date": date_str, "creneaux": slots})


@app.route("/reserver", methods=["POST"])
def reserver():
    data = request.json
    idobj = data.get("idobj")
    idcrt = data.get("idcrt", "2")
    pw = data.get("pw", "24")
    date_str = data.get("date", datetime.now().strftime("%d/%m/%Y"))
    if not idobj:
        return jsonify({"error": "idobj manquant"}), 400

    session, login_resp, _ = login()

    # Si date différente d'aujourd'hui, naviguer vers la bonne date
    today = datetime.now().strftime("%d/%m/%Y")
    if date_str != today:
        planning_resp = get_planning(session, login_resp, date_str)
        ref_resp = planning_resp
    else:
        ref_resp = login_resp

    # Ouvrir la fiche de réservation
    fiche_resp = open_reservation_form(session, ref_resp, idobj, idcrt, pw)

    # Sélectionner partenaire et valider
    confirm_resp = select_partner_and_validate(session, fiche_resp)

    soup = BeautifulSoup(confirm_resp.text, "lxml")
    erreur = soup.find(class_="erreur")
    if erreur and erreur.get_text(strip=True):
        return jsonify({"error": erreur.get_text(strip=True)})
    return jsonify({"status": "ok", "message": "Reservation confirmee"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
