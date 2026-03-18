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

COURT_NAMES = {
    "1": "Court 1TB", "2": "Court 2TB", "3": "Court 3TB", "4": "Court 4TB",
    "5": "Court 5TB", "6": "Court 6TB", "9": "Court 7DUR", "8": "Court 8DUR",
}


def get_md5(s):
    return hashlib.md5(s.upper().encode()).hexdigest()


def login():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.premier-service.fr",
    })
    r0 = session.get(f"https://www.premier-service.fr/_start/index.php?club={CLUB_ID}", allow_redirects=True)
    r1 = session.post(PLANNING_URL, data={"club": CLUB_ID, "idact": "101"}, headers={"Referer": r0.url})
    html = r1.text

    fl = fp = fm = idpge_val = action_url = None
    m = re.search(r'<form[^>]+action=["\']([^"\']+)["\']', html, re.I)
    if m: action_url = m.group(1)
    for m in re.finditer(r'<input[^>]+type=["\']text["\'][^>]*>', html, re.I):
        nm = re.search(r'name=["\'](\w+)["\']', m.group(0))
        if nm and nm.group(1) not in ("userid",): fl = nm.group(1); break
    for m in re.finditer(r'<input[^>]+type=["\']password["\'][^>]*>', html, re.I):
        nm = re.search(r'name=["\'](\w+)["\']', m.group(0))
        if nm and nm.group(1) not in ("userkey",): fp = nm.group(1); break
    fixed = {"idact","usermd5","idgfcmiid","largeur_ecran","hauteur_ecran","pingmax","pingmin","userid","userkey","idses","b_i","club"}
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
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\'](\d{3}-\d+)["\']', login_resp.text)
    if not m: m = re.search(r'value=["\'](\d{3}-\d+)["\'][^>]+name=["\']idpge["\']', login_resp.text)
    planning_idpge = m.group(1) if m else f"210-{CLUB_ID}"
    date_fr = format_date_fr(date_str)
    return session.post(PLANNING_URL, data={
        "idact": "336", "idpge": planning_idpge,
        "IDOBJ": "", "idses": "S0", "idcrt": "",
        "idpro": "", "idpar": "", "pw": "24", "dj": "2",
        "userid": "", "usermd5": "", "club": "",
        "B_MOJJO": "0",
        "LISTE_RESA_BOURSE_DATE_JEU": "",
        "LISTE_RESA_BOURSE_HEURE_JEU": "",
        "LISTE_RESA_BOURSE_COURT_JEU": "",
        "CHAMP_SELECTEUR_JEU": "1",
        "ID_TABLEAU": f"1|{CLUB_ID}|1",
        "CHAMP_SELECTEUR_JOUR": date_fr,
        "nc": "30",
    })


def parse_slots(html):
    """
    Parse les créneaux libres depuis la fonction JS idg_refresh_board.
    
    Logique :
    - idg_lset("8_0_C","22_0_C",-1,"var(--resa-libre)") = court C libre de 8h à 22h
    - idg_pset(Array("H_M_C",...)) = créneau H:M du court C occupé
    - Créneaux libres = heures pleines dans le range lset MINUS les pset occupés
    """
    slots = []

    # 1. Trouver tous les courts libres et leur range
    # Pattern: idg_lset("8_0_C","22_0_C",-1,"var(--resa-libre)")
    lset_pattern = re.compile(r'idg_lset\("(\d+)_0_(\d+)","(\d+)_0_\d+",-1,"var\(--resa-libre\)"\)')
    courts_libre = {}
    for m in lset_pattern.finditer(html):
        heure_debut = int(m.group(1))
        court = m.group(2)
        heure_fin = int(m.group(3))
        courts_libre[court] = (heure_debut, heure_fin)

    # 2. Trouver tous les créneaux occupés
    # Pattern: idg_pset(Array("H_M_C",...))
    pset_pattern = re.compile(r'idg_pset\(Array\("(\d+)_(\d+)_(\d+)"')
    occupied = set()
    for m in pset_pattern.finditer(html):
        heure = int(m.group(1))
        minutes = int(m.group(2))
        court = m.group(3)
        # On marque les heures pleines comme occupées
        if minutes == 0:
            occupied.add(f"{heure}_0_{court}")
        else:
            # Si demi-heure occupée, marquer l'heure pleine aussi
            occupied.add(f"{heure}_0_{court}")

    # 3. Créneaux libres = heures pleines dans range - occupés
    seen = set()
    for court, (h_debut, h_fin) in courts_libre.items():
        for heure in range(h_debut, h_fin):
            slot_id = f"{heure}_0_{court}"
            if slot_id not in occupied and slot_id not in seen:
                seen.add(slot_id)
                court_label = COURT_NAMES.get(court, f"Court {court}")
                slots.append({
                    "label": f"{court_label} - {heure}h",
                    "heure": f"{heure}h",
                    "court": court,
                    "court_label": court_label,
                    "slot_id": slot_id,
                })

    # Trier par heure puis court
    slots.sort(key=lambda x: (
        int(x["slot_id"].split("_")[0]),
        int(x["court"]) if x["court"].isdigit() else 99
    ))
    return slots


def open_reservation_and_validate(session, ref_html, slot_id, date_str):
    """Ouvre la fiche de réservation, sélectionne Aurelien et valide."""
    # Extraire idpge du planning
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\'](\d{3}-\d+)["\']', ref_html)
    if not m: m = re.search(r'value=["\'](\d{3}-\d+)["\'][^>]+name=["\']idpge["\']', ref_html)
    planning_idpge = m.group(1) if m else f"210-{CLUB_ID}"

    parts = slot_id.split("_")
    idcrt = parts[2] if len(parts) > 2 else "2"
    date_fr = format_date_fr(date_str)

    # Étape 1 : ouvrir la fiche de réservation
    fiche_resp = session.post(PLANNING_URL, data={
        "idact": "336", "idpge": planning_idpge,
        "IDOBJ": slot_id, "idses": "S0", "idcrt": idcrt,
        "idpro": "", "idpar": "", "pw": "24", "dj": "2",
        "userid": "", "usermd5": "", "club": "",
        "B_MOJJO": "0",
        "CHAMP_SELECTEUR_JEU": "1",
        "ID_TABLEAU": f"1|{CLUB_ID}|1",
        "CHAMP_SELECTEUR_JOUR": date_fr,
        "nc": "30",
    })

    # Extraire idpge de la fiche
    fiche_html = fiche_resp.text
    m = re.search(r'name=["\']idpge["\'][^>]+value=["\']([^"\']+)["\']', fiche_html)
    if not m: m = re.search(r'value=["\']([^"\']+)["\'][^>]+name=["\']idpge["\']', fiche_html)
    fiche_idpge = m.group(1) if m else ""

    # Vérifier qu'on a bien la fiche (pas une erreur)
    if "fiche_erreur" in fiche_html or "autorisations" in fiche_html:
        return False, "Impossible d'ouvrir la fiche de réservation"

    # Étape 2 : sélectionner Aurelien LANGE
    session.post(PLANNING_URL, data={
        "idact": "332", "idpge": fiche_idpge,
        "IDOBJ": "100", "IDREF": "", "idtpa": "",
        "idpar": "100", "rcout": "", "b_i": "0",
        "idses": "S0", "CHAMP_TYPE_1": PARTNER_VALUE,
    })

    # Étape 3 : valider
    confirm_resp = session.post(PLANNING_URL, data={
        "idact": "366", "idpge": fiche_idpge,
        "IDOBJ": "", "IDREF": "", "idtpa": "",
        "idpar": "", "rcout": "", "b_i": "0", "idses": "S0",
    })

    soup = BeautifulSoup(confirm_resp.text, "lxml")
    erreur = soup.find(class_="erreur")
    if erreur and erreur.get_text(strip=True):
        return False, erreur.get_text(strip=True)

    return True, "Reservation confirmee"


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/creneaux")
def creneaux():
    date_str = request.args.get("date", datetime.now().strftime("%d/%m/%Y"))
    session, login_resp, connected = login()
    if not connected:
        return jsonify({"error": "Echec de connexion"}), 401

    today = datetime.now().strftime("%d/%m/%Y")
    if date_str == today:
        html = login_resp.text
    else:
        resp = get_planning(session, login_resp, date_str)
        html = resp.text

    slots = parse_slots(html)
    return jsonify({"date": date_str, "creneaux": slots, "total": len(slots)})


@app.route("/reserver", methods=["POST"])
def reserver():
    data = request.json
    slot_id = data.get("slot_id")
    date_str = data.get("date", datetime.now().strftime("%d/%m/%Y"))
    if not slot_id:
        return jsonify({"error": "slot_id manquant"}), 400

    session, login_resp, connected = login()
    if not connected:
        return jsonify({"error": "Echec de connexion"}), 401

    today = datetime.now().strftime("%d/%m/%Y")
    if date_str == today:
        ref_html = login_resp.text
    else:
        resp = get_planning(session, login_resp, date_str)
        ref_html = resp.text

    success, message = open_reservation_and_validate(session, ref_html, slot_id, date_str)
    if success:
        return jsonify({"status": "ok", "message": message})
    return jsonify({"error": message}), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
