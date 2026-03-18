import os
import re
import base64
from datetime import datetime
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright

app = Flask(__name__)

CLUB_ID = "57920393"
LOGIN = os.environ.get("TENNIS_LOGIN", "JECHAP")
PASSWORD = os.environ.get("TENNIS_PASSWORD", "")
PARTNER_NAME = os.environ.get("TENNIS_PARTNER", "Aurelien LANGE")
PLANNING_URL = f"https://www.premier-service.fr/_start/index.php?club={CLUB_ID}"

COURT_NAMES = {
    "1": "Court 1TB", "2": "Court 2TB", "3": "Court 3TB", "4": "Court 4TB",
    "5": "Court 5TB", "6": "Court 6TB", "7": "Court 7DUR", "8": "Court 8DUR",
}


def make_browser(p):
    return p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
    )


def do_login(page):
    page.goto(PLANNING_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)

    # Chercher les champs visibles
    inputs_text = page.query_selector_all("input[type='text']")
    inputs_pwd = page.query_selector_all("input[type='password']")

    for inp in inputs_text:
        if inp.is_visible():
            inp.fill(LOGIN)
            break

    for inp in inputs_pwd:
        if inp.is_visible():
            inp.fill(PASSWORD)
            break

    # Cliquer sur le bouton Entrer
    btns = page.query_selector_all("button")
    for btn in btns:
        if btn.is_visible():
            txt = btn.inner_text().lower()
            if "entrer" in txt or "valider" in txt or "login" in txt:
                btn.click()
                break

    # Attendre que le planning charge
    page.wait_for_timeout(5000)


def get_slots(page):
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
            "slot_id": slot_id,
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
        if delta > 0:
            btns = page.query_selector_all("span")
            for btn in btns:
                if ">>" in btn.inner_text():
                    btn.click()
                    page.wait_for_timeout(2000)
                    break
        else:
            btns = page.query_selector_all("span")
            for btn in btns:
                if "<<" in btn.inner_text():
                    btn.click()
                    page.wait_for_timeout(2000)
                    break


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/debug-screenshot")
def debug_screenshot():
    """Prend une capture d'écran après login pour voir ce qui se passe."""
    try:
        with sync_playwright() as p:
            browser = make_browser(p)
            page = browser.new_page()
            do_login(page)
            # Capture d'écran en base64
            screenshot = page.screenshot()
            screenshot_b64 = base64.b64encode(screenshot).decode()
            # HTML de la page
            html = page.content()
            prc_count = len(page.query_selector_all("p.prc_visible"))
            ondblclick_count = len(page.query_selector_all("[ondblclick]"))
            url = page.url
            title = page.title()
            browser.close()
        return jsonify({
            "url": url,
            "title": title,
            "prc_visible_count": prc_count,
            "ondblclick_count": ondblclick_count,
            "html_length": len(html),
            "html_snippet": html[:2000],
            "screenshot_base64": screenshot_b64[:500],  # Juste le début pour vérifier
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
            el = page.query_selector(f"#{slot_id}")
            if not el:
                browser.close()
                return jsonify({"error": f"Creneau {slot_id} introuvable"}), 404
            el.dblclick()
            page.wait_for_timeout(3000)
            selects = page.query_selector_all("select:visible")
            for sel in selects:
                options = sel.query_selector_all("option")
                for opt in options:
                    if PARTNER_NAME.lower() in opt.inner_text().lower():
                        opt.click()
                        page.wait_for_timeout(3000)
                        break
            btns = page.query_selector_all("button:visible")
            for btn in btns:
                if "valider" in btn.inner_text().lower():
                    btn.click()
                    page.wait_for_timeout(3000)
                    break
            body_text = page.query_selector("body").inner_text()
            browser.close()
        if "erreur" in body_text.lower():
            return jsonify({"error": body_text[:300]}), 400
        return jsonify({"status": "ok", "message": "Reservation confirmee"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
