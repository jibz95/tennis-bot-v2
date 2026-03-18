import os
import re
from datetime import datetime
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright

app = Flask(__name__)

CLUB_ID = "57920393"
LOGIN = os.environ.get("TENNIS_LOGIN", "JECHAP")
PASSWORD = os.environ.get("TENNIS_PASSWORD", "")
PARTNER_NAME = os.environ.get("TENNIS_PARTNER", "Aurelien LANGE")
PLANNING_URL = f"https://www.premier-service.fr/_start/index.php?club={CLUB_ID}"

JOURS_FR = {0:"Lundi",1:"Mardi",2:"Mercredi",3:"Jeudi",4:"Vendredi",5:"Samedi",6:"Dimanche"}
COURT_NAMES = {
    "1": "Court 1TB", "2": "Court 2TB", "3": "Court 3TB", "4": "Court 4TB",
    "5": "Court 5TB", "6": "Court 6TB", "7": "Court 7DUR", "8": "Court 8DUR",
}


def do_login(page):
    page.goto(PLANNING_URL)
    page.wait_for_selector("input[type='text']:visible", timeout=10000)
    inputs_text = page.query_selector_all("input[type='text']:visible")
    inputs_pwd = page.query_selector_all("input[type='password']:visible")
    if inputs_text:
        inputs_text[0].fill(LOGIN)
    if inputs_pwd:
        inputs_pwd[0].fill(PASSWORD)
    btns = page.query_selector_all("button:visible")
    for btn in btns:
        txt = btn.inner_text().lower()
        if "entrer" in txt or "valider" in txt:
            btn.click()
            break
    page.wait_for_selector("p.prc_visible", timeout=15000)


def navigate_to_date(page, date_str):
    today = datetime.now().strftime("%d/%m/%Y")
    if date_str == today:
        return
    target = datetime.strptime(date_str, "%d/%m/%Y")
    current = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    delta = (target - current).days
    for _ in range(abs(delta)):
        if delta > 0:
            btn = page.query_selector("span:has-text('>>')")
        else:
            btn = page.query_selector("span:has-text('<<')")
        if btn:
            btn.click()
            page.wait_for_timeout(1000)


def get_slots(page):
    page.wait_for_selector("p.prc_visible", timeout=10000)
    elements = page.query_selector_all("p.prc_visible[ondblclick]")
    slots = []
    seen = set()
    for el in elements:
        slot_id = el.get_attribute("id")
        if not slot_id or slot_id in seen:
            continue
        parts = slot_id.split("_")
        if len(parts) < 3:
            continue
        heure_num, minutes, court = parts[0], parts[1], parts[2]
        if minutes != "0":
            continue
        seen.add(slot_id)
        heure = f"{heure_num}h"
        court_label = COURT_NAMES.get(court, f"Court {court}")
        slots.append({
            "label": f"{court_label} - {heure}",
            "heure": heure,
            "court": court,
            "court_label": court_label,
            "slot_id": slot_id,
        })
    slots.sort(key=lambda x: (
        int(x["slot_id"].split("_")[0]),
        int(x["court"]) if x["court"].isdigit() else 99
    ))
    return slots


def reserve_slot(page, slot_id):
    el = page.query_selector(f"#{slot_id}")
    if not el:
        return False, f"Créneau {slot_id} introuvable"
    el.dblclick()
    page.wait_for_selector("select:visible", timeout=10000)
    selects = page.query_selector_all("select:visible")
    for sel in selects:
        options = sel.query_selector_all("option")
        for opt in options:
            if PARTNER_NAME.lower() in opt.inner_text().lower():
                opt.click()
                page.wait_for_timeout(2000)
                break
    btns = page.query_selector_all("button:visible")
    for btn in btns:
        if "valider" in btn.inner_text().lower():
            btn.click()
            page.wait_for_timeout(2000)
            break
    body = page.query_selector("body")
    text = body.inner_text() if body else ""
    if "erreur" in text.lower():
        return False, text[:300]
    return True, "Reservation confirmee"


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/creneaux")
def creneaux():
    date_str = request.args.get("date", datetime.now().strftime("%d/%m/%Y"))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            do_login(page)
            navigate_to_date(page, date_str)
            slots = get_slots(page)
            browser.close()
        return jsonify({"date": date_str, "creneaux": slots})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/reserver", methods=["POST"])
def reserver():
    data = request.json
    slot_id = data.get("slot_id")
    date_str = data.get("date", datetime.now().strftime("%d/%m/%Y"))
    if not slot_id:
        return jsonify({"error": "slot_id manquant"}), 400
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            do_login(page)
            navigate_to_date(page, date_str)
            success, message = reserve_slot(page, slot_id)
            browser.close()
        if success:
            return jsonify({"status": "ok", "message": message})
        return jsonify({"error": message}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
