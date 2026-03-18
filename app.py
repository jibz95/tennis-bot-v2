import os
import hashlib
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

BASE_URL = "https://www.premier-service.fr/5.11.04/ics.php"
CLUB_ID = "32920393"

LOGIN = os.environ.get("TENNIS_LOGIN", "JECHAP")
PASSWORD = os.environ.get("TENNIS_PASSWORD", "")
PARTNER_NAME = os.environ.get("TENNIS_PARTNER", "Aurelien LANGE")


def get_md5(password):
    return hashlib.md5(password.encode()).hexdigest()


def login():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Referer": BASE_URL,
        "Origin": "https://www.premier-service.fr",
    })

    # Charger la page initiale pour récupérer idpge et autres tokens
    resp = session.get(
        f"https://www.adsltennis.fr/_start/index.php?club={CLUB_ID}&idact=101"
    )

    payload = {
        "idact": "101",
        "idpge": f"101-{CLUB_ID}",
        "usermd5": "",
        "rfeudimaisekeavstyte": get_md5(PASSWORD),
        "idgfcmiid": "0",
        "largeur_ecran": "1536",
        "hauteur_ecran": "864",
        "pingmax": "401",
        "pingmin": "18",
        "userid": "",
        "userkey": "",
        "iarphpsyudeayd": LOGIN,
        "ojsuykrfneeutasr": PASSWORD,
    }

    resp = session.post(BASE_URL, data=payload)
    if resp.status_code == 200:
        return session
    return None


def get_slots(session, date_str):
    """
    date_str : format JJ/MM/AAAA ex: 20/03/2026
    Retourne la liste des créneaux libres : [{court, heure, idres}]
    """
    # Navigation vers la page planning avec la date
    payload = {
        "idact": "349",
        "ladate": date_str,
    }
    resp = session.post(BASE_URL, data=payload)
    soup = BeautifulSoup(resp.text, "html.parser")

    slots = []
    # Les créneaux libres sont des liens cliquables sans réservation
    # On cherche les cellules vides (juste une heure, pas de nom)
    cells = soup.find_all("td", class_=lambda c: c and "libre" in c.lower())
    for cell in cells:
        link = cell.find("a")
        if link and link.get("href"):
            href = link["href"]
            # Extraire court et heure depuis href ou data attributes
            court = cell.get("data-court", "")
            heure = cell.get("data-heure", link.text.strip())
            idres = cell.get("data-idres", "")
            slots.append({
                "court": court,
                "heure": heure,
                "idres": idres,
                "label": f"Court {court} - {heure}"
            })

    return slots


def get_partner_id(session, partner_name):
    """Récupère l'ID du partenaire depuis le formulaire de réservation."""
    resp = session.post(BASE_URL, data={"idact": "349"})
    soup = BeautifulSoup(resp.text, "html.parser")
    select = soup.find("select", {"name": lambda n: n and "partenaire" in n.lower()})
    if select:
        for option in select.find_all("option"):
            if partner_name.lower() in option.text.lower():
                return option["value"]
    return None


def reserve(session, idres, partner_id):
    """Valide la réservation."""
    payload = {
        "idact": "349",
        "idres": idres,
        "idpartenaire": partner_id,
        "valider": "1",
    }
    resp = session.post(BASE_URL, data=payload)
    return resp.status_code == 200


# --- Routes Flask ---

@app.route("/creneaux", methods=["GET"])
def creneaux():
    date_str = request.args.get("date")  # format: JJ/MM/AAAA
    if not date_str:
        return jsonify({"error": "Parametre 'date' manquant"}), 400

    session = login()
    if not session:
        return jsonify({"error": "Echec de connexion"}), 401

    slots = get_slots(session, date_str)
    return jsonify({"date": date_str, "creneaux": slots})


@app.route("/reserver", methods=["POST"])
def reserver():
    data = request.json
    idres = data.get("idres")
    if not idres:
        return jsonify({"error": "Parametre 'idres' manquant"}), 400

    session = login()
    if not session:
        return jsonify({"error": "Echec de connexion"}), 401

    partner_id = get_partner_id(session, PARTNER_NAME)
    if not partner_id:
        return jsonify({"error": f"Partenaire '{PARTNER_NAME}' introuvable"}), 404

    success = reserve(session, idres, partner_id)
    if success:
        return jsonify({"status": "ok", "message": "Reservation confirmee"})
    else:
        return jsonify({"error": "Echec de la reservation"}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
