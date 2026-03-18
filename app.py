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


def extract_login_fields(html):
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
        "club": CLUB_ID, "idact": "101",
    }, headers={"Referer": r0.url})

    html = r1.text
    fl, fp, fm, idpge_val, action_url = extract_login_fields(html)

    md5 = get_md5(PASSWORD + LOGIN)
    post_url = action_url if (action_url and action_url.startswith("http")) else PLANNING_URL
    post_url = post_url.replace("/_start/../5.11.04/", "/5.11.04/").replace("?", "")

    payload = {
        "idact": "101",
        "idpge": idpge_val or f"101-{CLUB_ID}",
        "usermd5": "", "idgfcmiid": "0",
        "largeur_ecran": "1536", "hauteur_ecran": "864",
        "pingmax": "401", "pingmin": "18",
        "userid": "", "userkey": "",
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
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y")
        return f"{date_str} {JOURS_FR[dt.weekday()]}"
    except:
        return date_str


def get_planning(session, date_str):
    # Extraire idpge depuis la page de login si disponible
    date_fr = format_date_fr(date_str)
    payload = {
        "idact": "336",
        "idpge": "210-00000000000000",
        "IDOBJ": "10_0_2",
        "idses": "S0", "idcrt": "2",
        "idpro": "", "idpar": "",
        "pw": "14", "dj": "2",
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
    Les créneaux libres ont onclick avec idact=330 et IDOBJ=10_0_2_8h_1 etc.
    Format onclick: document.forms[0].idact.value='330';
                    document.forms[0].IDOBJ.value='10_0_2_8h_1';
                    document.forms[0].idcrt.value='1';
                    document.forms[0].pw.value='14';
    """
    slots = []
    # Chercher tous les éléments avec onclick contenant idact='330'
    pattern = re.compile(r"onclick=\"[^\"]*idact\.value='330'[^\"]*\"", re.I)
    
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(onclick=True):
        onclick = tag.get("onclick", "")
        if "idact.value='330'" in onclick or 'idact.value="330"' in onclick:
            # Extraire IDOBJ (contient court + heure)
            idobj_m = re.search(r"IDOBJ\.value='([^']+)'", onclick)
            idcrt_m = re.search(r"idcrt\.value='([^']+)'", onclick)
            pw_m = re.search(r"pw\.value='([^']+)'", onclick)
            
            idobj = idobj_m.group(1) if idobj_m else ""
            idcrt = idcrt_m.group(1) if idcrt_m else ""
            pw = pw_m.group(1) if pw_m else ""
            
            # Parser IDOBJ : format 10_0_2_8h_1 (site_?_court_heure_?)
            parts = idobj.split("_") if idobj else []
            heure = parts[3] if len(parts) > 3 else ""
            court = parts[2] if len(parts) > 2 else ""
            
            label = tag.get_text(strip=True) or heure
            
            slots.append({
                "label": f"Court {court} - {heure}" if court and heure else label,
                "heure": heure,
                "court": court,
                "idobj": idobj,
                "idcrt": idcrt,
                "pw": pw,
            })
    return slots


def reserve_slot(session, idobj, idcrt, pw, planning_idpge):
    """Clique sur un créneau libre pour ouvrir la fiche de réservation."""
    payload = {
        "idact": "330",
        "idpge": planning_idpge,
        "IDOBJ": idobj,
        "idcrt": idcrt,
        "pw": pw,
        "idses": "S0", "dj": "2",
        "B_MOJJO": "0",
        "CHAMP_SELECTEUR_JEU": "1",
        "ID_TABLEAU": f"1|{CLUB_ID}|1",
    }
    return session.post(PLANNING_URL, data=payload)


def select_partner_and_validate(session, fiche_html):
    """Depuis la fiche de réservation, sélectionne Aurelien et valide."""
    # Extraire idpge de la fiche
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\']([^"\']+)["\']', fiche_html)
    if not m:
        m = re.search(r'value=["\']([^"\']+)["\'][^>]+name=["\']idpge["\']', fiche_html)
    idpge = m.group(1) if m else ""

    # Étape 1 : sélectionner Aurelien LANGE (value=-100 -> IDOBJ=100)
    session.post(PLANNING_URL, data={
        "idact": "332", "idpge": idpge,
        "IDOBJ": "100", "idpar": "100",
        "CHAMP_TYPE_1": PARTNER_VALUE,
        "idses": "S0", "b_i": "0",
    })

    # Étape 2 : valider
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


@app.route("/debug-search")
def debug_search():
    date_str = request.args.get("date", "20/03/2026")
    term = request.args.get("term", "330")
    session, login_resp, connected = login()
    today = datetime.now().strftime("%d/%m/%Y")
    if date_str == today:
        html = login_resp.text
    else:
        resp = get_planning(session, date_str)
        html = resp.text
    # Chercher toutes les occurrences du terme
    snippets = []
    idx = 0
    while True:
        pos = html.find(term, idx)
        if pos == -1 or len(snippets) >= 5:
            break
        snippets.append(html[max(0,pos-100):pos+200])
        idx = pos + 1
    return jsonify({
        "html_length": len(html),
        "term": term,
        "occurrences": len(re.findall(re.escape(term), html)),
        "snippets": snippets,
    })


@app.route("/debug-planning")
def debug_planning():
    date_str = request.args.get("date", "19/03/2026")
    session, login_resp, connected = login()

    # D'abord essayer depuis la réponse du login (planning du jour)
    slots = parse_slots(login_resp.text)

    # Si pas de slots ou date différente, appeler get_planning
    today = datetime.now().strftime("%d/%m/%Y")
    if not slots or date_str != today:
        resp = get_planning(session, date_str)
        slots = parse_slots(resp.text)
        planning_html = resp.text
    else:
        planning_html = login_resp.text

    return jsonify({
        "connected": connected,
        "planning_length": len(planning_html),
        "slots_found": len(slots),
        "slots": slots[:10],
        "planning_html": planning_html[:3000],
    })


@app.route("/creneaux")
def creneaux():
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Parametre 'date' manquant"}), 400

    session, login_resp, _ = login()
    today = datetime.now().strftime("%d/%m/%Y")

    if date_str == today:
        slots = parse_slots(login_resp.text)
    else:
        resp = get_planning(session, date_str)
        slots = parse_slots(resp.text)

    return jsonify({"date": date_str, "creneaux": slots})


@app.route("/reserver", methods=["POST"])
def reserver():
    data = request.json
    idobj = data.get("idobj")
    idcrt = data.get("idcrt", "2")
    pw = data.get("pw", "14")
    if not idobj:
        return jsonify({"error": "idobj manquant"}), 400

    session, login_resp, _ = login()

    # Extraire idpge du planning
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\']([^"\']+)["\']', login_resp.text)
    planning_idpge = m.group(1) if m else "210-00000000000000"

    # Ouvrir la fiche de réservation
    fiche_resp = reserve_slot(session, idobj, idcrt, pw, planning_idpge)

    # Sélectionner partenaire et valider
    confirm_resp = select_partner_and_validate(session, fiche_resp.text)

    soup = BeautifulSoup(confirm_resp.text, "lxml")
    erreur = soup.find(class_="erreur")
    if erreur and erreur.get_text(strip=True):
        return jsonify({"error": erreur.get_text(strip=True)})
    return jsonify({"status": "ok", "message": "Reservation confirmee"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
