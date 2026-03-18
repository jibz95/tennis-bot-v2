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
COURT_NAMES = {"1":"1TB","2":"2TB","3":"3TB","4":"4TB","5":"5TB","6":"6TB","7":"7DUR","8":"8DUR"}


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


def get_planning_idpge(html):
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\'](\d{3}-\d+)["\']', html)
    if not m: m = re.search(r'value=["\'](\d{3}-\d+)["\'][^>]+name=["\']idpge["\']', html)
    return m.group(1) if m else f"210-{CLUB_ID}"


def get_planning(session, login_resp, date_str):
    planning_idpge = get_planning_idpge(login_resp.text)
    date_fr = format_date_fr(date_str)
    payload = {
        "idact": "336",
        "idpge": planning_idpge,
        "IDOBJ": "", "idses": "S0", "idcrt": "",
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
    Les créneaux libres ont la classe CSS 'resa_libre' sur les <td>.
    On extrait leur onclick et leurs attributs pour récupérer IDOBJ, idcrt, pw.
    """
    soup = BeautifulSoup(html, "lxml")
    slots = []
    seen = set()

    # Chercher tous les éléments avec classe contenant "libre"
    for tag in soup.find_all(class_=re.compile(r'libre', re.I)):
        onclick = tag.get("onclick", "")
        text = tag.get_text(strip=True)

        # Extraire IDOBJ depuis onclick ou attributs data-*
        idobj = ""
        idobj_m = re.search(r"['\"]?IDOBJ['\"]?\s*,\s*['\"]([^'\"]+)['\"]", onclick, re.I)
        if not idobj_m:
            idobj_m = re.search(r"IDOBJ[^'\"]*['\"]([^'\"]+)['\"]", onclick, re.I)
        if idobj_m:
            idobj = idobj_m.group(1)
        if not idobj:
            idobj = tag.get("data-idobj", "") or tag.get("id", "")

        if not idobj or idobj in seen:
            continue
        seen.add(idobj)

        # Extraire idcrt et pw
        idcrt_m = re.search(r"['\"]?idcrt['\"]?\s*,\s*['\"]([^'\"]+)['\"]", onclick, re.I)
        pw_m = re.search(r"['\"]?pw['\"]?\s*,\s*['\"]([^'\"]+)['\"]", onclick, re.I)
        idcrt = idcrt_m.group(1) if idcrt_m else tag.get("data-idcrt", "2")
        pw = pw_m.group(1) if pw_m else tag.get("data-pw", "24")

        # Décoder IDOBJ pour extraire court et heure
        parts = idobj.split("_")
        court_num = parts[2] if len(parts) > 2 else "?"
        heure_num = parts[0] if parts else ""
        heure = f"{heure_num}h" if heure_num.isdigit() else (text if text else "?")

        slots.append({
            "label": f"Court {court_num} - {heure}",
            "heure": heure,
            "court": court_num,
            "idobj": idobj,
            "idcrt": idcrt,
            "pw": pw,
            "onclick_raw": onclick[:150],
        })

    slots.sort(key=lambda x: (
        int(x["heure"].replace("h","")) if x["heure"].replace("h","").isdigit() else 99,
        int(x["court"]) if x["court"].isdigit() else 99
    ))
    return slots


def open_reservation_form(session, ref_html, slot_id, date_str):
    """Ouvre la fiche de réservation pour un créneau (via idg_take)."""
    planning_idpge = get_planning_idpge(ref_html)
    date_fr = format_date_fr(date_str)

    # idg_take soumet le formulaire avec idact=336 et l'id du créneau comme IDOBJ
    payload = {
        "idact": "336",
        "idpge": planning_idpge,
        "IDOBJ": slot_id,
        "idses": "S0", "idcrt": slot_id.split("_")[2] if len(slot_id.split("_")) > 2 else "2",
        "idpro": "", "idpar": "",
        "pw": "24", "dj": "2",
        "userid": "", "usermd5": "", "club": "",
        "B_MOJJO": "0",
        "CHAMP_SELECTEUR_JEU": "1",
        "ID_TABLEAU": f"1|{CLUB_ID}|1",
        "CHAMP_SELECTEUR_JOUR": date_fr,
        "nc": "30",
    }
    return session.post(PLANNING_URL, data=payload)


def select_partner_and_validate(session, fiche_html):
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\']([^"\']+)["\']', fiche_html)
    if not m: m = re.search(r'value=["\']([^"\']+)["\'][^>]+name=["\']idpge["\']', fiche_html)
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
    return jsonify({"connected": connected, "resp_len": len(resp.text)})


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
    # Debug: compter les <p> avec prc_visible
    soup = BeautifulSoup(html, "lxml")
    prc_visible = soup.find_all("p", class_=lambda c: c and "prc_visible" in " ".join(c))
    resa_libre = [p for p in prc_visible if "--resa-libre" in p.get("style","")]
    return jsonify({
        "connected": connected,
        "planning_length": len(html),
        "prc_visible_count": len(prc_visible),
        "resa_libre_count": len(resa_libre),
        "slots_found": len(slots),
        "slots": slots,
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
    slot_id = data.get("slot_id")
    date_str = data.get("date", datetime.now().strftime("%d/%m/%Y"))
    if not slot_id:
        return jsonify({"error": "slot_id manquant"}), 400

    session, login_resp, _ = login()
    today = datetime.now().strftime("%d/%m/%Y")
    if date_str != today:
        planning_resp = get_planning(session, login_resp, date_str)
        ref_html = planning_resp.text
    else:
        ref_html = login_resp.text

    fiche_resp = open_reservation_form(session, ref_html, slot_id, date_str)
    confirm_resp = select_partner_and_validate(session, fiche_resp.text)

    soup = BeautifulSoup(confirm_resp.text, "lxml")
    erreur = soup.find(class_="erreur")
    if erreur and erreur.get_text(strip=True):
        return jsonify({"error": erreur.get_text(strip=True)})
    return jsonify({"status": "ok", "message": "Reservation confirmee"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
