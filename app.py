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
PLANNING_URL = "https://www.premier-service.fr/5.11.04/ics.php"
JOURS_FR = {0:"Lundi",1:"Mardi",2:"Mercredi",3:"Jeudi",4:"Vendredi",5:"Samedi",6:"Dimanche"}


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

    # Extraire les champs
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


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/debug-search")
def debug_search():
    date_str = request.args.get("date", datetime.now().strftime("%d/%m/%Y"))
    term = request.args.get("term", "prc_visible")
    session, login_resp, connected = login()
    today = datetime.now().strftime("%d/%m/%Y")
    if date_str == today:
        html = login_resp.text
    else:
        resp = get_planning(session, login_resp, date_str)
        html = resp.text
    snippets = []
    idx = 0
    while len(snippets) < 5:
        pos = html.find(term, idx)
        if pos == -1: break
        snippets.append(html[max(0,pos-100):pos+300])
        idx = pos + 1
    return jsonify({
        "connected": connected,
        "html_length": len(html),
        "term": term,
        "occurrences": html.count(term),
        "snippets": snippets,
    })


@app.route("/creneaux")
def creneaux():
    return jsonify({"error": "En cours de debug"}), 503


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
