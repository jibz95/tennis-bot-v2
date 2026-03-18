import os
import base64
from datetime import datetime
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

app = Flask(__name__)

CLUB_ID = "57920393"
LOGIN = os.environ.get("TENNIS_LOGIN", "JECHAP")
PASSWORD = os.environ.get("TENNIS_PASSWORD", "")
PARTNER_NAME = os.environ.get("TENNIS_PARTNER", "Aurelien LANGE")

COURT_NAMES = {
    "1": "Court 1TB", "2": "Court 2TB", "3": "Court 3TB", "4": "Court 4TB",
    "5": "Court 5TB", "6": "Court 6TB", "7": "Court 7DUR", "8": "Court 8DUR",
}


def make_browser(p):
    return p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
              "--disable-setuid-sandbox", "--single-process"]
    )


def do_login(page):
    # Aller sur la page de login
    page.goto(
        f"https://www.premier-service.fr/_start/index.php?club={CLUB_ID}",
        timeout=30000
    )
    # Attendre que la page se stabilise
    page.wait_for_load_state("load", timeout=30000)
    page.wait_for_timeout(3000)

    # Vérifier l'URL actuelle
    current_url = page.url

    # Si on est redirigé vers ics.php, attendre le formulaire de login
    page.wait_for_timeout(2000)

    # Prendre le contenu actuel
    html = page.content()

    # Chercher les champs de login
    inputs_text = page.locator("input[type='text']:visible")
    inputs_pwd = page.locator("input[type='password']:visible")

    if inputs_text.count() > 0:
        inputs_text.first.fill(LOGIN)
    if inputs_pwd.count() > 0:
        inputs_pwd.first.fill(PASSWORD)

    # Cliquer Entrer
    for text in ["Entrer", "Valider", "Login", "Se connecter"]:
        btn = page.locator(f"button:has-text('{text}')")
        if btn.count() > 0:
            btn.first.click()
            break

    # Attendre le planning
    page.wait_for_load_state("load", timeout=30000)
    page.wait_for_timeout(5000)


def get_slots(page):
    elements = page.locator("p.prc_visible[ondblclick]").all()
    slots = []
    seen = set()
    for el in elements:
        slot_id = el.get_attribute("id")
        if not slot_id or slot_id in seen:
            continue
        parts = slot_id.split("_")
        if len(parts) < 3 or parts[1] != "0":
            continue
        seen.add(slot_id)
        heure_num, court = parts[0], parts[2]
        heure = f"{heure_num}h"
        slots.append({
            "label": f"{COURT_NAMES.get(court, f'Court {court}')} - {heure}",
            "heure": heure, "court": court, "slot_id": slot_id,
        })
    slots.sort(key=lambda x: (int(x["slot_id"].split("_")[0]), int(x["court"]) if x["court"].isdigit() else 99))
    return slots


def navigate_to_date(page, date_str):
    today = datetime.now().strftime("%d/%m/%Y")
    if date_str == today:
        return
    target = datetime.strptime(date_str, "%d/%m/%Y")
    current = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    delta = (target - current).days
    for _ in range(abs(delta)):
        selector = ">>" if delta > 0 else "<<"
        btn = page.locator(f"text='{selector}'")
        if btn.count() > 0:
            btn.first.click()
            page.wait_for_timeout(2000)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/debug-screenshot")
def debug_screenshot():
    try:
        with sync_playwright() as p:
            browser = make_browser(p)
            page = browser.new_page()
            do_login(page)
            screenshot = page.screenshot()
            html = page.content()
            prc_count = page.locator("p.prc_visible").count()
            ondbl_count = page.locator("[ondblclick]").count()
            url = page.url
            title = page.title()
            browser.close()
        return jsonify({
            "url": url, "title": title,
            "prc_visible_count": prc_count,
            "ondblclick_count": ondbl_count,
            "html_length": len(html),
            "html_snippet": html[:3000],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/creneaux")
def creneaux():
    date_str = request.args.get("date", datetime.now().strftime("%d/%m/%Y"))
    try:
        with sync_playwright() as p:
            browser = make_browser(p)
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
            browser = make_browser(p)
            page = browser.new_page()
            do_login(page)
            navigate_to_date(page, date_str)
            el = page.locator(f"#{slot_id}")
            if el.count() == 0:
                browser.close()
                return jsonify({"error": f"Creneau {slot_id} introuvable"}), 404
            el.dblclick()
            page.wait_for_timeout(3000)
            for sel in page.locator("select:visible").all():
                for opt in sel.locator("option").all():
                    if PARTNER_NAME.lower() in opt.inner_text().lower():
                        opt.click()
                        page.wait_for_timeout(3000)
                        break
            valider = page.locator("button:has-text('Valider')")
            if valider.count() > 0:
                valider.first.click()
                page.wait_for_timeout(3000)
            body_text = page.locator("body").inner_text()
            browser.close()
        if "erreur" in body_text.lower():
            return jsonify({"error": body_text[:300]}), 400
        return jsonify({"status": "ok", "message": "Reservation confirmee"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
